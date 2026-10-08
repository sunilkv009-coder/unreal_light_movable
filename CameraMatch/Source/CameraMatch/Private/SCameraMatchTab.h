#pragma once

#include "CoreMinimal.h"
#include "Engine/Texture2D.h"
#include "Input/Reply.h"
#include "UObject/StrongObjectPtr.h"
#include "UObject/WeakObjectPtrTemplates.h"
#include "Widgets/DeclarativeSyntaxSupport.h"
#include "Widgets/SCompoundWidget.h"

#include "CameraMatchScene.h"

class ACineCameraActor;
class SCameraMatchCanvas;
struct FCameraMatchDocument;

/**
 * The "Camera Match" tab: an fSpy-style camera matcher inside the editor.
 *
 * Left: the photo, the method (one or two vanishing points), the axes, the lens, the scale,
 * the overlay options, the solved camera and the camera buttons. Right: the photo with the
 * control lines. Creating a camera spawns a Cine Camera with the solved transform, filmback
 * and focal length, and a post-process backplate that shows the photo through it.
 */
class SCameraMatchTab : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SCameraMatchTab) {}
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs);
	virtual ~SCameraMatchTab() override;

private:
	TSharedRef<SWidget> MakeSidePanel();
	TSharedRef<SWidget> MakeAxisPicker(TFunction<int32()> Get, TFunction<void(int32)> Set, bool bSigned);
	TSharedRef<SWidget> MakeNumberRow(const FText& Label, const FText& InTooltip, TFunction<double()> Get, TFunction<void(double)> Set,
		TAttribute<bool> InEnabled, TAttribute<EVisibility> InVisibility);
	TSharedRef<SWidget> MakeCheckRow(const FText& Label, const FText& InTooltip, TFunction<bool()> Get, TFunction<void(bool)> Set);

	void SetImage(UTexture2D* Texture, int32 Width, int32 Height, const FString& InSourceFile, UTexture2D* InPlate, const FString& Name,
		bool bResetHandles);

	/** Solves again, repaints and (if live update is on) moves the linked camera. */
	void Resolve();
	void OnHandlesChanged();
	void OnDragStarted();
	void OnDragFinished();
	void ApplyLive();
	void ApplyBackplateOptions();
	void SaveStateTo(ACineCameraActor* Camera) const;

	/** The photo as a texture asset, importing the file the first time it's needed. */
	UTexture2D* GetPlateTexture(FText& OutError);

	FReply OnLoadImageClicked();
	FReply OnUseTextureClicked();
	FReply OnCreateCameraClicked();
	FReply OnUpdateCameraClicked();
	FReply OnPilotClicked();
	FReply OnEditSelectedClicked();
	FReply OnResetLinesClicked();
	FReply OnFitClicked();

	FText GetImageText() const;
	FText GetHintText() const;
	FText GetResultText() const;
	FText GetErrorText() const;
	FText GetWarningsText() const;
	FText GetLinkedText() const;
	FText GetStatusText() const;
	FSlateColor GetStatusColor() const;
	void SetStatus(const FText& Text, bool bError);

	TSharedPtr<FCameraMatchDocument> Document;
	TSharedPtr<SCameraMatchCanvas> Canvas;

	/** What the canvas shows (a transient texture for files, or the asset). */
	TStrongObjectPtr<UTexture2D> DisplayTexture;
	/** The texture asset used for the backplate. */
	TStrongObjectPtr<UTexture2D> PlateTexture;
	FString SourceFile;
	FString ImageName;
	FString LastDirectory;

	/** The camera that Update Camera and live updates change. */
	TWeakObjectPtr<ACineCameraActor> LinkedCamera;

	CameraMatchScene::FBackplateOptions Backplate;
	bool bAddBackplate = true;
	bool bLiveUpdate = true;
	bool bDragTransactionOpen = false;

	FText Status;
	bool bStatusIsError = false;
};
