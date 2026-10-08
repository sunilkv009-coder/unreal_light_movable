#include "SCameraMatchTab.h"

#include "AssetRegistry/AssetData.h"
#include "CineCameraActor.h"
#include "CineCameraComponent.h"
#include "ContentBrowserModule.h"
#include "DesktopPlatformModule.h"
#include "Editor.h"
#include "Framework/Application/SlateApplication.h"
#include "IContentBrowserSingleton.h"
#include "IDesktopPlatform.h"
#include "ImageUtils.h"
#include "Misc/Attribute.h"
#include "Misc/Paths.h"
#include "Modules/ModuleManager.h"
#include "ScopedTransaction.h"
#include "Selection.h"
#include "Styling/AppStyle.h"
#include "Styling/CoreStyle.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Input/SCheckBox.h"
#include "Widgets/Input/SNumericEntryBox.h"
#include "Widgets/Input/SSegmentedControl.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SScrollBox.h"
#include "Widgets/Layout/SSplitter.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/Text/STextBlock.h"

#include "CameraMatchDocument.h"
#include "SCameraMatchCanvas.h"

#define LOCTEXT_NAMESPACE "CameraMatch"

namespace CameraMatchTabPrivate
{
	/** Actor, root and camera component, so moving and re-lensing the camera can be undone. */
	void ModifyCamera(ACineCameraActor* Camera)
	{
		Camera->Modify();
		if (USceneComponent* Root = Camera->GetRootComponent())
		{
			Root->Modify();
		}
		if (UCineCameraComponent* Component = Camera->GetCineCameraComponent())
		{
			Component->Modify();
		}
	}

	FText FromUtf8(const std::string& Text)
	{
		return FText::FromString(FString(UTF8_TO_TCHAR(Text.c_str())));
	}
}

void SCameraMatchTab::Construct(const FArguments& InArgs)
{
	Document = MakeShared<FCameraMatchDocument>();

	ChildSlot
	[
		SNew(SSplitter)
		.Orientation(Orient_Horizontal)
		+ SSplitter::Slot()
		.Value(0.3f)
		[
			SNew(SBorder)
			.BorderImage(FAppStyle::GetBrush("ToolPanel.GroupBorder"))
			.Padding(0.f)
			[
				SNew(SScrollBox)
				+ SScrollBox::Slot()
				[
					MakeSidePanel()
				]
			]
		]
		+ SSplitter::Slot()
		.Value(0.7f)
		[
			SNew(SVerticalBox)
			+ SVerticalBox::Slot()
			.AutoHeight()
			.Padding(6.f, 4.f)
			[
				SNew(SHorizontalBox)
				+ SHorizontalBox::Slot()
				.AutoWidth()
				.Padding(0.f, 0.f, 6.f, 0.f)
				[
					SNew(SButton)
					.Text(LOCTEXT("Fit", "Fit (F)"))
					.ToolTipText(LOCTEXT("FitTip", "Show the whole photo."))
					.OnClicked(this, &SCameraMatchTab::OnFitClicked)
				]
				+ SHorizontalBox::Slot()
				.AutoWidth()
				.Padding(0.f, 0.f, 12.f, 0.f)
				[
					SNew(SButton)
					.Text(LOCTEXT("ResetLines", "Reset Lines"))
					.ToolTipText(LOCTEXT("ResetLinesTip", "Put the lines and handles back in their starting layout."))
					.IsEnabled_Lambda([this]() { return Document->bHasImage; })
					.OnClicked(this, &SCameraMatchTab::OnResetLinesClicked)
				]
				+ SHorizontalBox::Slot()
				.FillWidth(1.f)
				.VAlign(VAlign_Center)
				[
					SNew(STextBlock)
					.Text(this, &SCameraMatchTab::GetHintText)
					.AutoWrapText(true)
					.ColorAndOpacity(FSlateColor::UseSubduedForeground())
				]
			]
			+ SVerticalBox::Slot()
			.FillHeight(1.f)
			[
				SAssignNew(Canvas, SCameraMatchCanvas)
				.Document(Document)
				.OnHandlesChanged(this, &SCameraMatchTab::OnHandlesChanged)
				.OnDragStarted(this, &SCameraMatchTab::OnDragStarted)
				.OnDragFinished(this, &SCameraMatchTab::OnDragFinished)
			]
		]
	];
}

SCameraMatchTab::~SCameraMatchTab()
{
	if (bDragTransactionOpen && GEditor)
	{
		GEditor->EndTransaction();
	}
}

TSharedRef<SWidget> SCameraMatchTab::MakeSidePanel()
{
	using CameraMatch::EScaleMode;
	using CameraMatch::ESolveMode;

	TSharedRef<SVerticalBox> Box = SNew(SVerticalBox);
	auto Heading = [&Box](const FText& Text)
	{
		Box->AddSlot()
		.AutoHeight()
		.Padding(10.f, 14.f, 10.f, 4.f)
		[
			SNew(STextBlock)
			.Text(Text)
			.Font(FCoreStyle::GetDefaultFontStyle("Bold", 11))
		];
	};
	auto Row = [&Box](const TSharedRef<SWidget>& Widget)
	{
		Box->AddSlot()
		.AutoHeight()
		.Padding(10.f, 3.f, 10.f, 0.f)
		[
			Widget
		];
	};
	auto Help = [&Row](const TAttribute<FText>& Text)
	{
		Row(SNew(STextBlock)
			.Text(Text)
			.AutoWrapText(true)
			.Font(FCoreStyle::GetDefaultFontStyle("Regular", 8))
			.ColorAndOpacity(FSlateColor::UseSubduedForeground()));
	};
	auto Label = [&Row](const TAttribute<FText>& Text)
	{
		Row(SNew(STextBlock).Text(Text));
	};
	auto IsMode = [this](ESolveMode Mode)
	{
		return Document->Input.Mode == Mode;
	};
	auto ScaleVisibility = [this](EScaleMode Mode)
	{
		return TAttribute<EVisibility>::CreateLambda([this, Mode]()
		{
			return Document->Input.Scale == Mode ? EVisibility::Visible : EVisibility::Collapsed;
		});
	};
	// Overlay options only change the drawing, not the camera.
	auto Redraw = [this]()
	{
		if (Canvas.IsValid())
		{
			Canvas->Invalidate(EInvalidateWidgetReason::Paint);
		}
	};
	const TAttribute<bool> Always(true);
	const TAttribute<EVisibility> Visible(EVisibility::Visible);

	// 1. Photo
	Heading(LOCTEXT("PhotoHeading", "1. Photo"));
	Row(SNew(SHorizontalBox)
		+ SHorizontalBox::Slot()
		.AutoWidth()
		.Padding(0.f, 0.f, 6.f, 0.f)
		[
			SNew(SButton)
			.Text(LOCTEXT("LoadImage", "Load Image File..."))
			.ToolTipText(LOCTEXT("LoadImageTip", "Open a photo from disk (PNG, JPG, BMP, TGA, EXR, TIFF). It's imported into /Game/CameraMatch/Backplates when you create the camera."))
			.OnClicked(this, &SCameraMatchTab::OnLoadImageClicked)
		]
		+ SHorizontalBox::Slot()
		.AutoWidth()
		[
			SNew(SButton)
			.Text(LOCTEXT("UseTexture", "Use Selected Texture"))
			.ToolTipText(LOCTEXT("UseTextureTip", "Use the texture selected in the Content Browser."))
			.OnClicked(this, &SCameraMatchTab::OnUseTextureClicked)
		]);
	Help(TAttribute<FText>::CreateLambda([this]() { return GetImageText(); }));

	// 2. Method
	Heading(LOCTEXT("MethodHeading", "2. Method"));
	Row(SNew(SSegmentedControl<int32>)
		.Value_Lambda([this]() { return static_cast<int32>(Document->Input.Mode); })
		.OnValueChanged_Lambda([this](int32 Value)
		{
			Document->Input.Mode = static_cast<ESolveMode>(Value);
			Resolve();
		})
		+ SSegmentedControl<int32>::Slot(static_cast<int32>(ESolveMode::TwoVanishingPoints))
		.Text(LOCTEXT("TwoVP", "2 vanishing points"))
		+ SSegmentedControl<int32>::Slot(static_cast<int32>(ESolveMode::OneVanishingPoint))
		.Text(LOCTEXT("OneVP", "1 vanishing point")));
	Help(TAttribute<FText>::CreateLambda([IsMode]()
	{
		return IsMode(ESolveMode::TwoVanishingPoints)
			? LOCTEXT("TwoVPHelp", "Two sets of parallel edges at 90 degrees to each other, like the two sides of a building, a room or a box. Works out the focal length.")
			: LOCTEXT("OneVPHelp", "One set of parallel edges, plus the direction of the horizon, like a road or corridor seen head on. You enter the focal length.");
	}));

	// 3. Axes
	Heading(LOCTEXT("AxesHeading", "3. Axes"));
	Help(LOCTEXT("AxesHelp", "For each set of lines, pick the Unreal axis the edges run along, in the direction towards where the lines meet. X is red, Y green, Z blue (up)."));
	Label(LOCTEXT("Axis1", "Vanishing point 1"));
	Row(MakeAxisPicker(
		[this]() { return static_cast<int32>(Document->Input.Axis1); },
		[this](int32 Value) { Document->Input.Axis1 = static_cast<CameraMatch::EWorldAxis>(Value); Resolve(); },
		true));
	Label(TAttribute<FText>::CreateLambda([IsMode]()
	{
		return IsMode(ESolveMode::TwoVanishingPoints)
			? LOCTEXT("Axis2Two", "Vanishing point 2")
			: LOCTEXT("Axis2One", "Horizon line (the arrow points along this axis)");
	}));
	Row(MakeAxisPicker(
		[this]() { return static_cast<int32>(Document->Input.Axis2); },
		[this](int32 Value) { Document->Input.Axis2 = static_cast<CameraMatch::EWorldAxis>(Value); Resolve(); },
		true));

	// 4. Lens
	Heading(LOCTEXT("LensHeading", "4. Lens"));
	Row(MakeNumberRow(
		LOCTEXT("Sensor", "Sensor size, long side (mm)"),
		LOCTEXT("SensorTip", "Size of the camera sensor along the photo's longer side: 36 for full frame, 23.5 for APS-C, 17.3 for Micro Four Thirds. If you don't know it, keep 36: it changes the focal length number, not the match."),
		[this]() { return Document->Input.SensorMM; },
		[this](double Value) { Document->Input.SensorMM = FMath::Max(Value, 0.1); Resolve(); },
		Always, Visible));
	Row(MakeNumberRow(
		LOCTEXT("Focal", "Focal length (mm)"),
		LOCTEXT("FocalTip", "The lens focal length the photo was taken with (see its EXIF data). Only the 1 vanishing point method needs it; the 2 point method works it out."),
		[this]() { return Document->Input.FocalMM; },
		[this](double Value) { Document->Input.FocalMM = FMath::Max(Value, 0.1); Resolve(); },
		Always,
		TAttribute<EVisibility>::CreateLambda([IsMode]() { return IsMode(ESolveMode::OneVanishingPoint) ? EVisibility::Visible : EVisibility::Collapsed; })));

	// 5. Scale
	Heading(LOCTEXT("ScaleHeading", "5. Scale"));
	Row(SNew(SSegmentedControl<int32>)
		.Value_Lambda([this]() { return static_cast<int32>(Document->Input.Scale); })
		.OnValueChanged_Lambda([this](int32 Value)
		{
			Document->Input.Scale = static_cast<EScaleMode>(Value);
			Resolve();
		})
		+ SSegmentedControl<int32>::Slot(static_cast<int32>(EScaleMode::CameraDistance))
		.Text(LOCTEXT("ScaleDistance", "Distance"))
		+ SSegmentedControl<int32>::Slot(static_cast<int32>(EScaleMode::CameraHeight))
		.Text(LOCTEXT("ScaleHeight", "Camera height"))
		+ SSegmentedControl<int32>::Slot(static_cast<int32>(EScaleMode::ReferenceLength))
		.Text(LOCTEXT("ScaleReference", "Known length")));
	Help(TAttribute<FText>::CreateLambda([this]()
	{
		switch (Document->Input.Scale)
		{
		case EScaleMode::CameraHeight:
			return LOCTEXT("ScaleHeightHelp", "The camera is this high above the ground the origin stands on. About 150-170 cm for a hand-held photo.");
		case EScaleMode::ReferenceLength:
			return LOCTEXT("ScaleReferenceHelp", "Drag the reference handle along the chosen axis from the origin to a point at a known distance (a door width, a car's wheelbase, a floor tile), and enter that distance.");
		default:
			return LOCTEXT("ScaleDistanceHelp", "The camera is this far from the origin. Use this when the real size doesn't matter.");
		}
	}));
	Row(MakeNumberRow(
		LOCTEXT("Distance", "Distance to origin (cm)"), FText::GetEmpty(),
		[this]() { return Document->Input.CameraDistance; },
		[this](double Value) { Document->Input.CameraDistance = FMath::Max(Value, 0.1); Resolve(); },
		Always, ScaleVisibility(EScaleMode::CameraDistance)));
	Row(MakeNumberRow(
		LOCTEXT("Height", "Camera height (cm)"), FText::GetEmpty(),
		[this]() { return Document->Input.CameraHeight; },
		[this](double Value) { Document->Input.CameraHeight = FMath::Max(Value, 0.1); Resolve(); },
		Always, ScaleVisibility(EScaleMode::CameraHeight)));
	Row(MakeNumberRow(
		LOCTEXT("Length", "Known length (cm)"), FText::GetEmpty(),
		[this]() { return Document->Input.ReferenceLength; },
		[this](double Value) { Document->Input.ReferenceLength = FMath::Max(Value, 0.1); Resolve(); },
		Always, ScaleVisibility(EScaleMode::ReferenceLength)));
	Row(SNew(SBox)
		.Visibility(ScaleVisibility(EScaleMode::ReferenceLength))
		[
			MakeAxisPicker(
				[this]() { return Document->Input.ReferenceAxis; },
				[this](int32 Value) { Document->Input.ReferenceAxis = Value; Resolve(); },
				false)
		]);
	Help(LOCTEXT("OriginHelp", "The Origin handle is where the world origin (0,0,0) goes: put it on the ground, on a corner you know."));

	// 6. Overlay
	Heading(LOCTEXT("OverlayHeading", "6. Overlay"));
	Row(MakeCheckRow(LOCTEXT("ShowGrid", "Ground grid and axes"), LOCTEXT("ShowGridTip", "Draw the ground (Z = 0) with the solved camera. If the camera matches, the grid lies flat on the ground in the photo."),
		[this]() { return Document->bShowGrid; },
		[this, Redraw](bool bValue) { Document->bShowGrid = bValue; Redraw(); }));
	Row(MakeNumberRow(
		LOCTEXT("GridSize", "Grid cell size (cm)"), FText::GetEmpty(),
		[this]() { return Document->GridSpacing; },
		[this, Redraw](double Value) { Document->GridSpacing = FMath::Max(Value, 1.0); Redraw(); },
		TAttribute<bool>::CreateLambda([this]() { return Document->bShowGrid; }), Visible));
	Row(MakeCheckRow(LOCTEXT("ShowHorizon", "Horizon line"), LOCTEXT("ShowHorizonTip", "Draw the solved camera's horizon (eye level)."),
		[this]() { return Document->bShowHorizon; },
		[this, Redraw](bool bValue) { Document->bShowHorizon = bValue; Redraw(); }));
	Row(MakeCheckRow(LOCTEXT("ShowExtended", "Extend the lines"), LOCTEXT("ShowExtendedTip", "Continue the control lines across the view, to see where they meet."),
		[this]() { return Document->bShowExtendedLines; },
		[this, Redraw](bool bValue) { Document->bShowExtendedLines = bValue; Redraw(); }));

	// Result
	Heading(LOCTEXT("ResultHeading", "Solved camera"));
	Row(SNew(STextBlock)
		.Text(this, &SCameraMatchTab::GetErrorText)
		.AutoWrapText(true)
		.ColorAndOpacity(FLinearColor(1.f, 0.4f, 0.35f))
		.Visibility_Lambda([this]() { return GetErrorText().IsEmpty() ? EVisibility::Collapsed : EVisibility::Visible; }));
	Row(SNew(STextBlock)
		.Text(this, &SCameraMatchTab::GetWarningsText)
		.AutoWrapText(true)
		.ColorAndOpacity(FLinearColor(1.f, 0.7f, 0.2f))
		.Visibility_Lambda([this]() { return GetWarningsText().IsEmpty() ? EVisibility::Collapsed : EVisibility::Visible; }));
	Row(SNew(STextBlock)
		.Text(this, &SCameraMatchTab::GetResultText)
		.Font(FCoreStyle::GetDefaultFontStyle("Mono", 9)));

	// 7. Unreal camera
	Heading(LOCTEXT("CameraHeading", "7. Unreal camera"));
	Row(MakeCheckRow(LOCTEXT("AddBackplate", "Show the photo through the camera (backplate)"),
		LOCTEXT("AddBackplateTip", "Adds a post-process material to the camera that shows the photo in its view, exactly framed. Only this camera shows it."),
		[this]() { return bAddBackplate; },
		[this](bool bValue) { bAddBackplate = bValue; }));
	Row(MakeNumberRow(
		LOCTEXT("Opacity", "Backplate opacity (0-1)"),
		LOCTEXT("OpacityTip", "0.5 lets you see the 3D scene and the photo together, to check the match. 1 shows only the photo."),
		[this]() { return static_cast<double>(Backplate.Opacity); },
		[this](double Value) { Backplate.Opacity = static_cast<float>(FMath::Clamp(Value, 0.0, 1.0)); ApplyBackplateOptions(); },
		TAttribute<bool>::CreateLambda([this]() { return bAddBackplate; }), Visible));
	Row(MakeCheckRow(LOCTEXT("Behind", "Photo only behind 3D objects"),
		LOCTEXT("BehindTip", "Show the photo only where nothing is rendered (empty space and sky), so 3D objects sit in front of it."),
		[this]() { return Backplate.bBehindScene; },
		[this](bool bValue) { Backplate.bBehindScene = bValue; ApplyBackplateOptions(); }));
	Row(MakeCheckRow(LOCTEXT("Live", "Live update the linked camera"),
		LOCTEXT("LiveTip", "Move the linked camera while you drag the lines or change settings. Each drag is one undo step."),
		[this]() { return bLiveUpdate; },
		[this](bool bValue) { bLiveUpdate = bValue; }));
	Row(SNew(SHorizontalBox)
		+ SHorizontalBox::Slot()
		.AutoWidth()
		.Padding(0.f, 4.f, 6.f, 0.f)
		[
			SNew(SButton)
			.Text(LOCTEXT("CreateCamera", "Create Camera"))
			.ToolTipText(LOCTEXT("CreateCameraTip", "Add a Cine Camera to the open level with the solved position, rotation, filmback and focal length."))
			.IsEnabled_Lambda([this]() { return Document->Result.bValid; })
			.OnClicked(this, &SCameraMatchTab::OnCreateCameraClicked)
		]
		+ SHorizontalBox::Slot()
		.AutoWidth()
		.Padding(0.f, 4.f, 0.f, 0.f)
		[
			SNew(SButton)
			.Text(LOCTEXT("UpdateCamera", "Update Camera"))
			.ToolTipText(LOCTEXT("UpdateCameraTip", "Apply the current solve and backplate settings to the linked camera."))
			.IsEnabled_Lambda([this]() { return Document->Result.bValid && LinkedCamera.IsValid(); })
			.OnClicked(this, &SCameraMatchTab::OnUpdateCameraClicked)
		]);
	Row(SNew(SHorizontalBox)
		+ SHorizontalBox::Slot()
		.AutoWidth()
		.Padding(0.f, 4.f, 6.f, 0.f)
		[
			SNew(SButton)
			.Text(LOCTEXT("Pilot", "Pilot Camera"))
			.ToolTipText(LOCTEXT("PilotTip", "Look through the linked (or selected) camera in the level viewport."))
			.OnClicked(this, &SCameraMatchTab::OnPilotClicked)
		]
		+ SHorizontalBox::Slot()
		.AutoWidth()
		.Padding(0.f, 4.f, 0.f, 0.f)
		[
			SNew(SButton)
			.Text(LOCTEXT("EditSelected", "Edit Selected Camera"))
			.ToolTipText(LOCTEXT("EditSelectedTip", "Reopen the lines and settings of a camera made with this tool (select it in the level first)."))
			.OnClicked(this, &SCameraMatchTab::OnEditSelectedClicked)
		]);
	Help(TAttribute<FText>::CreateLambda([this]() { return GetLinkedText(); }));
	Box->AddSlot()
	.AutoHeight()
	.Padding(10.f, 8.f, 10.f, 14.f)
	[
		SNew(STextBlock)
		.Text(this, &SCameraMatchTab::GetStatusText)
		.ColorAndOpacity(this, &SCameraMatchTab::GetStatusColor)
		.AutoWrapText(true)
	];

	return Box;
}

TSharedRef<SWidget> SCameraMatchTab::MakeAxisPicker(TFunction<int32()> Get, TFunction<void(int32)> Set, bool bSigned)
{
	if (!bSigned)
	{
		return SNew(SSegmentedControl<int32>)
			.Value_Lambda([Get]() { return Get(); })
			.OnValueChanged_Lambda([Set](int32 Value) { Set(Value); })
			+ SSegmentedControl<int32>::Slot(0).Text(LOCTEXT("AxisX", "X"))
			+ SSegmentedControl<int32>::Slot(1).Text(LOCTEXT("AxisY", "Y"))
			+ SSegmentedControl<int32>::Slot(2).Text(LOCTEXT("AxisZ", "Z"));
	}
	return SNew(SSegmentedControl<int32>)
		.Value_Lambda([Get]() { return Get(); })
		.OnValueChanged_Lambda([Set](int32 Value) { Set(Value); })
		+ SSegmentedControl<int32>::Slot(static_cast<int32>(CameraMatch::EWorldAxis::PosX)).Text(LOCTEXT("PosX", "+X"))
		+ SSegmentedControl<int32>::Slot(static_cast<int32>(CameraMatch::EWorldAxis::NegX)).Text(LOCTEXT("NegX", "-X"))
		+ SSegmentedControl<int32>::Slot(static_cast<int32>(CameraMatch::EWorldAxis::PosY)).Text(LOCTEXT("PosY", "+Y"))
		+ SSegmentedControl<int32>::Slot(static_cast<int32>(CameraMatch::EWorldAxis::NegY)).Text(LOCTEXT("NegY", "-Y"))
		+ SSegmentedControl<int32>::Slot(static_cast<int32>(CameraMatch::EWorldAxis::PosZ)).Text(LOCTEXT("PosZ", "+Z"))
		+ SSegmentedControl<int32>::Slot(static_cast<int32>(CameraMatch::EWorldAxis::NegZ)).Text(LOCTEXT("NegZ", "-Z"));
}

TSharedRef<SWidget> SCameraMatchTab::MakeNumberRow(const FText& Label, const FText& InTooltip, TFunction<double()> Get,
	TFunction<void(double)> Set, TAttribute<bool> InEnabled, TAttribute<EVisibility> InVisibility)
{
	return SNew(SHorizontalBox)
		.IsEnabled(InEnabled)
		.Visibility(InVisibility)
		.ToolTipText(InTooltip)
		+ SHorizontalBox::Slot()
		.FillWidth(1.f)
		.VAlign(VAlign_Center)
		[
			SNew(STextBlock)
			.Text(Label)
		]
		+ SHorizontalBox::Slot()
		.FillWidth(0.7f)
		[
			SNew(SNumericEntryBox<double>)
			.AllowSpin(false)
			.Value_Lambda([Get]() { return TOptional<double>(Get()); })
			.OnValueCommitted_Lambda([Set](double Value, ETextCommit::Type CommitType) { Set(Value); })
		];
}

TSharedRef<SWidget> SCameraMatchTab::MakeCheckRow(const FText& Label, const FText& InTooltip, TFunction<bool()> Get, TFunction<void(bool)> Set)
{
	return SNew(SCheckBox)
		.ToolTipText(InTooltip)
		.IsChecked_Lambda([Get]() { return Get() ? ECheckBoxState::Checked : ECheckBoxState::Unchecked; })
		.OnCheckStateChanged_Lambda([Set](ECheckBoxState NewState) { Set(NewState == ECheckBoxState::Checked); })
		[
			SNew(STextBlock)
			.Text(Label)
		];
}

void SCameraMatchTab::SetImage(UTexture2D* Texture, int32 Width, int32 Height, const FString& InSourceFile, UTexture2D* InPlate,
	const FString& Name, bool bResetHandles)
{
	OnDragFinished();
	DisplayTexture.Reset(Texture);
	PlateTexture.Reset(InPlate);
	SourceFile = InSourceFile;
	ImageName = Name;
	LinkedCamera.Reset();

	Document->ImageBrush = FSlateBrush();
	Document->ImageBrush.SetResourceObject(Texture);
	Document->ImageBrush.DrawAs = ESlateBrushDrawType::Image;
	Document->bHasImage = true;
	Document->Input.ImageWidth = Width;
	Document->Input.ImageHeight = Height;
	if (bResetHandles)
	{
		CameraMatch::ResetHandles(Document->Input);
	}
	if (Canvas.IsValid())
	{
		Canvas->RequestFit();
	}
	Resolve();
}

void SCameraMatchTab::Resolve()
{
	Document->Solve();
	if (Canvas.IsValid())
	{
		Canvas->Invalidate(EInvalidateWidgetReason::Paint);
	}
	ApplyLive();
}

void SCameraMatchTab::OnHandlesChanged()
{
	Resolve();
}

void SCameraMatchTab::OnDragStarted()
{
	ACineCameraActor* Camera = LinkedCamera.Get();
	if (!bLiveUpdate || !Camera || !GEditor || bDragTransactionOpen)
	{
		return;
	}
	// One undo step for the whole drag.
	GEditor->BeginTransaction(LOCTEXT("AdjustCamera", "Adjust Camera Match camera"));
	CameraMatchTabPrivate::ModifyCamera(Camera);
	bDragTransactionOpen = true;
}

void SCameraMatchTab::OnDragFinished()
{
	if (!bDragTransactionOpen)
	{
		return;
	}
	if (ACineCameraActor* Camera = LinkedCamera.Get())
	{
		SaveStateTo(Camera);
		Camera->PostEditMove(true);
	}
	bDragTransactionOpen = false;
	if (GEditor)
	{
		GEditor->EndTransaction();
	}
}

void SCameraMatchTab::ApplyLive()
{
	ACineCameraActor* Camera = LinkedCamera.Get();
	if (!bLiveUpdate || !Camera || !Document->Result.bValid)
	{
		return;
	}
	if (bDragTransactionOpen)
	{
		// Already recorded for undo when the drag started; the state tag is written when it ends.
		CameraMatchScene::ApplyCamera(Camera, Document->Result);
		return;
	}
	const FScopedTransaction Transaction(LOCTEXT("AdjustCamera", "Adjust Camera Match camera"));
	CameraMatchTabPrivate::ModifyCamera(Camera);
	CameraMatchScene::ApplyCamera(Camera, Document->Result);
	SaveStateTo(Camera);
	Camera->PostEditMove(true);
}

void SCameraMatchTab::ApplyBackplateOptions()
{
	ACineCameraActor* Camera = LinkedCamera.Get();
	if (!Camera || !CameraMatchScene::SetBackplateOptions(Camera, Backplate))
	{
		return;
	}
	const FScopedTransaction Transaction(LOCTEXT("BackplateOptions", "Change Camera Match backplate"));
	Camera->Modify();
	SaveStateTo(Camera);
}

void SCameraMatchTab::SaveStateTo(ACineCameraActor* Camera) const
{
	CameraMatchScene::WriteState(Camera, Document->Input, PlateTexture.IsValid() ? PlateTexture->GetPathName() : FString(), SourceFile, Backplate);
}

UTexture2D* SCameraMatchTab::GetPlateTexture(FText& OutError)
{
	if (PlateTexture.IsValid())
	{
		return PlateTexture.Get();
	}
	if (SourceFile.IsEmpty())
	{
		OutError = LOCTEXT("NoPhotoFile", "Load the photo first.");
		return nullptr;
	}
	UTexture2D* Imported = CameraMatchScene::ImportBackplateTexture(SourceFile, OutError);
	if (Imported)
	{
		PlateTexture.Reset(Imported);
	}
	return Imported;
}

FReply SCameraMatchTab::OnLoadImageClicked()
{
	IDesktopPlatform* Desktop = FDesktopPlatformModule::Get();
	if (!Desktop)
	{
		return FReply::Handled();
	}
	TArray<FString> Files;
	const void* ParentWindow = FSlateApplication::Get().FindBestParentWindowHandleForDialogs(AsShared());
	const bool bPicked = Desktop->OpenFileDialog(ParentWindow, LOCTEXT("PickPhoto", "Choose the backplate photo").ToString(), LastDirectory, FString(),
		TEXT("Images (*.png;*.jpg;*.jpeg;*.bmp;*.tga;*.exr;*.tif;*.tiff)|*.png;*.jpg;*.jpeg;*.bmp;*.tga;*.exr;*.tif;*.tiff"),
		EFileDialogFlags::None, Files);
	if (!bPicked || Files.Num() == 0)
	{
		return FReply::Handled();
	}

	const FString File = FPaths::ConvertRelativePathToFull(Files[0]);
	LastDirectory = FPaths::GetPath(File);
	UTexture2D* Texture = FImageUtils::ImportFileAsTexture2D(File);
	if (!Texture || Texture->GetSizeX() <= 0 || Texture->GetSizeY() <= 0)
	{
		SetStatus(FText::Format(LOCTEXT("ReadFailed", "Couldn't read {0}. Use a PNG, JPG, BMP, TGA, EXR or TIFF file."), FText::FromString(File)), true);
		return FReply::Handled();
	}
	SetImage(Texture, Texture->GetSizeX(), Texture->GetSizeY(), File, nullptr, FPaths::GetBaseFilename(File), true);
	SetStatus(LOCTEXT("Loaded", "Photo loaded. Drag the line handles onto edges in the photo."), false);
	return FReply::Handled();
}

FReply SCameraMatchTab::OnUseTextureClicked()
{
	FContentBrowserModule& ContentBrowser = FModuleManager::LoadModuleChecked<FContentBrowserModule>("ContentBrowser");
	TArray<FAssetData> Selected;
	ContentBrowser.Get().GetSelectedAssets(Selected);
	UTexture2D* Texture = nullptr;
	for (const FAssetData& Asset : Selected)
	{
		Texture = Cast<UTexture2D>(Asset.GetAsset());
		if (Texture)
		{
			break;
		}
	}
	if (!Texture)
	{
		SetStatus(LOCTEXT("NoTextureSelected", "Select a texture in the Content Browser first."), true);
		return FReply::Handled();
	}

	// Full resolution, so the handles can be placed precisely.
	Texture->SetForceMipLevelsToBeResident(30.f);
	int32 Width = Texture->GetSizeX();
	int32 Height = Texture->GetSizeY();
#if WITH_EDITORONLY_DATA
	if (Texture->Source.IsValid())
	{
		Width = static_cast<int32>(Texture->Source.GetSizeX());
		Height = static_cast<int32>(Texture->Source.GetSizeY());
	}
#endif
	if (Width <= 0 || Height <= 0)
	{
		SetStatus(LOCTEXT("EmptyTexture", "That texture has no image data."), true);
		return FReply::Handled();
	}
	SetImage(Texture, Width, Height, FString(), Texture, Texture->GetName(), true);

	FText Error;
	if (CameraMatchScene::CanUseAsBackplate(Texture, Error))
	{
		SetStatus(LOCTEXT("TextureLoaded", "Texture loaded. Drag the line handles onto edges in the photo."), false);
	}
	else
	{
		SetStatus(Error, true);
	}
	return FReply::Handled();
}

FReply SCameraMatchTab::OnCreateCameraClicked()
{
	const CameraMatch::FResult& Result = Document->Result;
	if (!Result.bValid)
	{
		SetStatus(LOCTEXT("NotSolved", "The camera can't be solved yet: fix the lines first."), true);
		return FReply::Handled();
	}

	FText Error;
	UTexture2D* Plate = nullptr;
	if (bAddBackplate)
	{
		Plate = GetPlateTexture(Error);
		if (!Plate)
		{
			SetStatus(Error, true);
			return FReply::Handled();
		}
	}

	FScopedTransaction Transaction(LOCTEXT("CreateCameraTransaction", "Create Camera Match camera"));
	ACineCameraActor* Camera = CameraMatchScene::CreateCamera(Result, TEXT("CameraMatch_") + ImageName, Error);
	if (!Camera)
	{
		Transaction.Cancel();
		SetStatus(Error, true);
		return FReply::Handled();
	}
	const bool bBackplateOk = !Plate || CameraMatchScene::SetBackplate(Camera, Plate, Backplate, Error);
	SaveStateTo(Camera);
	LinkedCamera = Camera;
	GEditor->SelectNone(false, true);
	GEditor->SelectActor(Camera, true, true);

	if (bBackplateOk)
	{
		SetStatus(FText::Format(
			LOCTEXT("Created", "Created {0}. Click Pilot Camera to look through it. Save the level, and the new assets in /Game/CameraMatch, to keep it."),
			FText::FromString(Camera->GetActorLabel())), false);
	}
	else
	{
		SetStatus(FText::Format(LOCTEXT("CreatedNoBackplate", "Created {0}, but without the backplate: {1}"),
			FText::FromString(Camera->GetActorLabel()), Error), true);
	}
	return FReply::Handled();
}

FReply SCameraMatchTab::OnUpdateCameraClicked()
{
	ACineCameraActor* Camera = LinkedCamera.Get();
	const CameraMatch::FResult& Result = Document->Result;
	if (!Camera || !Result.bValid)
	{
		SetStatus(LOCTEXT("NothingToUpdate", "No linked camera, or the camera can't be solved yet."), true);
		return FReply::Handled();
	}

	FText Error;
	UTexture2D* Plate = nullptr;
	if (bAddBackplate)
	{
		Plate = GetPlateTexture(Error);
		if (!Plate)
		{
			SetStatus(Error, true);
			return FReply::Handled();
		}
	}

	const FScopedTransaction Transaction(LOCTEXT("UpdateCameraTransaction", "Update Camera Match camera"));
	CameraMatchTabPrivate::ModifyCamera(Camera);
	CameraMatchScene::ApplyCamera(Camera, Result);
	bool bBackplateOk = true;
	if (Plate)
	{
		bBackplateOk = CameraMatchScene::SetBackplate(Camera, Plate, Backplate, Error);
	}
	else
	{
		CameraMatchScene::RemoveBackplate(Camera);
	}
	SaveStateTo(Camera);
	Camera->PostEditMove(true);
	GEditor->NoteSelectionChange();

	if (bBackplateOk)
	{
		SetStatus(FText::Format(LOCTEXT("Updated", "Updated {0}."), FText::FromString(Camera->GetActorLabel())), false);
	}
	else
	{
		SetStatus(FText::Format(LOCTEXT("UpdatedNoBackplate", "Updated {0}, but not its backplate: {1}"),
			FText::FromString(Camera->GetActorLabel()), Error), true);
	}
	return FReply::Handled();
}

FReply SCameraMatchTab::OnPilotClicked()
{
	ACineCameraActor* Camera = LinkedCamera.Get();
	if (!Camera && GEditor)
	{
		TArray<ACineCameraActor*> Cameras;
		GEditor->GetSelectedActors()->GetSelectedObjects<ACineCameraActor>(Cameras);
		Camera = Cameras.Num() > 0 ? Cameras[0] : nullptr;
	}
	if (!Camera)
	{
		SetStatus(LOCTEXT("NoCameraToPilot", "Create a camera first, or select a Cine Camera in the level."), true);
		return FReply::Handled();
	}
	CameraMatchScene::Pilot(Camera);
	SetStatus(FText::Format(
		LOCTEXT("Piloting", "Looking through {0}. To stop, click the eject button at the top left of the viewport. Press G for Game View to hide the editor icons."),
		FText::FromString(Camera->GetActorLabel())), false);
	return FReply::Handled();
}

FReply SCameraMatchTab::OnEditSelectedClicked()
{
	TArray<ACineCameraActor*> Cameras;
	if (GEditor)
	{
		GEditor->GetSelectedActors()->GetSelectedObjects<ACineCameraActor>(Cameras);
	}
	if (Cameras.Num() == 0)
	{
		SetStatus(LOCTEXT("SelectCamera", "Select a camera made with Camera Match in the level first."), true);
		return FReply::Handled();
	}

	ACineCameraActor* Camera = Cameras[0];
	CameraMatch::FInput Input;
	FString TexturePath;
	FString File;
	CameraMatchScene::FBackplateOptions Options;
	if (!CameraMatchScene::ReadState(Camera, Input, TexturePath, File, Options))
	{
		SetStatus(FText::Format(LOCTEXT("NotOurs", "{0} wasn't made with Camera Match, so there are no lines to reopen."),
			FText::FromString(Camera->GetActorLabel())), true);
		return FReply::Handled();
	}

	UTexture2D* Asset = TexturePath.IsEmpty() ? nullptr : LoadObject<UTexture2D>(nullptr, *TexturePath, nullptr, LOAD_NoWarn | LOAD_Quiet);
	UTexture2D* Display = Asset;
	if (!Display && !File.IsEmpty() && FPaths::FileExists(File))
	{
		Display = FImageUtils::ImportFileAsTexture2D(File);
	}
	if (!Display)
	{
		SetStatus(FText::Format(LOCTEXT("PhotoMissing", "Can't find the photo of {0} ({1}). Load it again, set the lines, then use Update Camera."),
			FText::FromString(Camera->GetActorLabel()), FText::FromString(TexturePath.IsEmpty() ? File : TexturePath)), true);
		return FReply::Handled();
	}
	if (Asset)
	{
		Asset->SetForceMipLevelsToBeResident(30.f);
	}

	SetImage(Display, static_cast<int32>(Input.ImageWidth), static_cast<int32>(Input.ImageHeight), File, Asset,
		Asset ? Asset->GetName() : FPaths::GetBaseFilename(File), false);
	Document->Input = Input;
	Backplate = Options;
	LinkedCamera = Camera;
	Document->Solve();
	if (Canvas.IsValid())
	{
		Canvas->RequestFit();
	}
	SetStatus(FText::Format(LOCTEXT("Editing", "Editing {0}. Changes apply to it live (if Live update is on), or with Update Camera."),
		FText::FromString(Camera->GetActorLabel())), false);
	return FReply::Handled();
}

FReply SCameraMatchTab::OnResetLinesClicked()
{
	if (Document->bHasImage)
	{
		CameraMatch::ResetHandles(Document->Input);
		Resolve();
	}
	return FReply::Handled();
}

FReply SCameraMatchTab::OnFitClicked()
{
	if (Canvas.IsValid())
	{
		Canvas->RequestFit();
	}
	return FReply::Handled();
}

FText SCameraMatchTab::GetImageText() const
{
	if (!Document->bHasImage)
	{
		return LOCTEXT("NoImage", "No photo yet.");
	}
	return FText::FromString(FString::Printf(TEXT("%s  (%d x %d)%s"), *ImageName,
		static_cast<int32>(Document->Input.ImageWidth), static_cast<int32>(Document->Input.ImageHeight),
		PlateTexture.IsValid() ? TEXT("") : TEXT("  - from a file, imported when a camera needs it")));
}

FText SCameraMatchTab::GetHintText() const
{
	if (!Document->bHasImage)
	{
		return LOCTEXT("HintNoImage", "Start by loading the photo (left).");
	}
	if (Document->Input.Mode == CameraMatch::ESolveMode::TwoVanishingPoints)
	{
		return LOCTEXT("HintTwo", "Put each pair of lines on two edges that are parallel in the real world: VP1 along one direction, VP2 along one at 90 degrees to it. Then put the Origin on the ground.");
	}
	return LOCTEXT("HintOne", "Put the VP1 lines on two parallel edges, turn the horizon line to follow the horizon (its arrow points along its axis), and enter the focal length.");
}

FText SCameraMatchTab::GetResultText() const
{
	const CameraMatch::FResult& Result = Document->Result;
	if (!Document->bHasImage || !Result.bValid)
	{
		return FText::GetEmpty();
	}
	return FText::FromString(FString::Printf(
		TEXT("Focal length   %.2f mm\nSensor         %.2f x %.2f mm\nField of view  %.2f x %.2f deg\nLocation       X %.1f  Y %.1f  Z %.1f\nRotation       P %.2f  Y %.2f  R %.2f\nTo origin      %.1f cm"),
		Result.FocalMM, Result.SensorWidthMM, Result.SensorHeightMM, Result.HorizontalFovDeg, Result.VerticalFovDeg,
		Result.Location.X, Result.Location.Y, Result.Location.Z, Result.Pitch, Result.Yaw, Result.Roll, Result.DistanceToOrigin));
}

FText SCameraMatchTab::GetErrorText() const
{
	if (!Document->bHasImage || Document->Result.bValid)
	{
		return FText::GetEmpty();
	}
	return CameraMatchTabPrivate::FromUtf8(Document->Result.Error);
}

FText SCameraMatchTab::GetWarningsText() const
{
	if (!Document->bHasImage || !Document->Result.bValid)
	{
		return FText::GetEmpty();
	}
	FString Text;
	for (const std::string& Warning : Document->Result.Warnings)
	{
		Text += (Text.IsEmpty() ? TEXT("") : TEXT("\n")) + FString(UTF8_TO_TCHAR(Warning.c_str()));
	}
	return FText::FromString(Text);
}

FText SCameraMatchTab::GetLinkedText() const
{
	if (const ACineCameraActor* Camera = LinkedCamera.Get())
	{
		return FText::Format(LOCTEXT("Linked", "Linked camera: {0}"), FText::FromString(Camera->GetActorLabel()));
	}
	return LOCTEXT("NotLinked", "No linked camera. Create one, or select one made with this tool and click Edit Selected Camera.");
}

FText SCameraMatchTab::GetStatusText() const
{
	return Status;
}

FSlateColor SCameraMatchTab::GetStatusColor() const
{
	return bStatusIsError ? FSlateColor(FLinearColor(1.f, 0.4f, 0.35f)) : FSlateColor(FLinearColor(0.4f, 0.85f, 0.4f));
}

void SCameraMatchTab::SetStatus(const FText& Text, bool bError)
{
	Status = Text;
	bStatusIsError = bError;
}

#undef LOCTEXT_NAMESPACE
