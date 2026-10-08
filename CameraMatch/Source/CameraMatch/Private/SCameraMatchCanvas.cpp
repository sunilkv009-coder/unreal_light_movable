#include "SCameraMatchCanvas.h"

#include "Fonts/SlateFontInfo.h"
#include "InputCoreTypes.h"
#include "Layout/Clipping.h"
#include "Misc/EngineVersionComparison.h"
#include "Rendering/DrawElements.h"
#include "Styling/CoreStyle.h"

#include <type_traits>
#include <utility>

#include "CameraMatchDocument.h"

namespace CameraMatchCanvas
{
	// Slate moved to float vectors in 5.1.
#if UE_VERSION_OLDER_THAN(5, 1, 0)
	using FSlateVector = FVector2D;
#else
	using FSlateVector = FVector2f;
#endif
	using FUVBox = std::decay_t<decltype(std::declval<FSlateBrush>().GetUVRegion())>;
	using FUVVector = decltype(FUVBox::Min);
	using FUVScalar = decltype(FUVVector::X);

	constexpr double TwoPi = 6.283185307179586;
	constexpr float HandleRadius = 6.f;
	constexpr double HitRadius = 11.0;
	constexpr double LoupeSize = 170.0;
	constexpr double LoupeZoom = 4.0;

	FSlateVector ToSlate(const FVector2D& V)
	{
		return FSlateVector(static_cast<float>(V.X), static_cast<float>(V.Y));
	}

	FPaintGeometry RectGeometry(const FGeometry& Geometry, const FVector2D& Position, const FVector2D& Size)
	{
		return Geometry.ToPaintGeometry(ToSlate(Size), FSlateLayoutTransform(ToSlate(Position)));
	}

	FLinearColor AxisColor(int32 Axis, float Alpha = 1.f)
	{
		switch (Axis)
		{
		case 0:
			return FLinearColor(0.95f, 0.22f, 0.22f, Alpha);
		case 1:
			return FLinearColor(0.35f, 0.9f, 0.3f, Alpha);
		default:
			return FLinearColor(0.3f, 0.55f, 1.f, Alpha);
		}
	}

	/** Liang-Barsky: clips segment A-B (or the whole line through A and B) to a rectangle. */
	bool ClipToView(FVector2D& A, FVector2D& B, const FVector2D& Min, const FVector2D& Max, bool bInfiniteLine)
	{
		double T0 = bInfiniteLine ? -1e30 : 0.0;
		double T1 = bInfiniteLine ? 1e30 : 1.0;
		const FVector2D D = B - A;
		const double P[4] = {-D.X, D.X, -D.Y, D.Y};
		const double Q[4] = {A.X - Min.X, Max.X - A.X, A.Y - Min.Y, Max.Y - A.Y};
		for (int32 Side = 0; Side < 4; ++Side)
		{
			if (FMath::Abs(P[Side]) < 1e-12)
			{
				if (Q[Side] < 0.0)
				{
					return false;
				}
				continue;
			}
			const double R = Q[Side] / P[Side];
			if (P[Side] < 0.0)
			{
				if (R > T1)
				{
					return false;
				}
				T0 = FMath::Max(T0, R);
			}
			else
			{
				if (R < T0)
				{
					return false;
				}
				T1 = FMath::Min(T1, R);
			}
		}
		const FVector2D Start = A + D * T0;
		B = A + D * T1;
		A = Start;
		return true;
	}

	void DrawLine(FSlateWindowElementList& Out, int32 Layer, const FGeometry& Geometry, const FVector2D& A, const FVector2D& B,
		const FLinearColor& Color, float Thickness)
	{
		TArray<FSlateVector> Points;
		Points.Add(ToSlate(A));
		Points.Add(ToSlate(B));
		FSlateDrawElement::MakeLines(Out, Layer, Geometry.ToPaintGeometry(), Points, ESlateDrawEffect::None, Color, true, Thickness);
	}

	/** A line with a dark outline under it, so it reads on any photo. Uses Layer and Layer + 1. */
	void DrawOutlinedLine(FSlateWindowElementList& Out, int32 Layer, const FGeometry& Geometry, const FVector2D& A, const FVector2D& B,
		const FLinearColor& Color, float Thickness)
	{
		DrawLine(Out, Layer, Geometry, A, B, FLinearColor(0.f, 0.f, 0.f, 0.65f), Thickness + 2.f);
		DrawLine(Out, Layer + 1, Geometry, A, B, Color, Thickness);
	}

	void DrawCircle(FSlateWindowElementList& Out, int32 Layer, const FGeometry& Geometry, const FVector2D& Centre, double Radius,
		const FLinearColor& Color, float Thickness)
	{
		TArray<FSlateVector> Points;
		constexpr int32 Segments = 20;
		for (int32 Index = 0; Index <= Segments; ++Index)
		{
			const double Angle = TwoPi * Index / Segments;
			Points.Add(ToSlate(Centre + FVector2D(FMath::Cos(Angle), FMath::Sin(Angle)) * Radius));
		}
		FSlateDrawElement::MakeLines(Out, Layer, Geometry.ToPaintGeometry(), Points, ESlateDrawEffect::None, Color, true, Thickness);
	}

	/** Text with a drop shadow. Uses Layer and Layer + 1. */
	void DrawLabel(FSlateWindowElementList& Out, int32 Layer, const FGeometry& Geometry, const FVector2D& Position, const FString& Text,
		const FLinearColor& Color)
	{
		const FSlateFontInfo Font = FCoreStyle::GetDefaultFontStyle("Bold", 9);
		const FVector2D Box(1000.0, 20.0);
		FSlateDrawElement::MakeText(Out, Layer, RectGeometry(Geometry, Position + FVector2D(1.0, 1.0), Box), Text, Font,
			ESlateDrawEffect::None, FLinearColor(0.f, 0.f, 0.f, 0.9f));
		FSlateDrawElement::MakeText(Out, Layer + 1, RectGeometry(Geometry, Position, Box), Text, Font, ESlateDrawEffect::None, Color);
	}

	FString AxisText(CameraMatch::EWorldAxis Axis)
	{
		return FString(ANSI_TO_TCHAR(CameraMatch::AxisLabel(Axis)));
	}
}

void SCameraMatchCanvas::Construct(const FArguments& InArgs)
{
	Document = InArgs._Document;
	OnHandlesChanged = InArgs._OnHandlesChanged;
	OnDragStarted = InArgs._OnDragStarted;
	OnDragFinished = InArgs._OnDragFinished;
	SetClipping(EWidgetClipping::ClipToBounds);
}

void SCameraMatchCanvas::RequestFit()
{
	bFitPending = true;
	Invalidate(EInvalidateWidgetReason::Paint);
}

FVector2D SCameraMatchCanvas::ComputeDesiredSize(float LayoutScaleMultiplier) const
{
	return FVector2D(480.0, 320.0);
}

void SCameraMatchCanvas::GetView(const FVector2D& LocalSize, double& OutScale, FVector2D& OutOffset) const
{
	if (!bFitPending || !Document.IsValid() || !Document->bHasImage)
	{
		OutScale = ViewScale;
		OutOffset = ViewOffset;
		return;
	}
	const double Width = FMath::Max(Document->Input.ImageWidth, 1.0);
	const double Height = FMath::Max(Document->Input.ImageHeight, 1.0);
	const double Margin = 16.0;
	OutScale = FMath::Max(FMath::Min((LocalSize.X - 2.0 * Margin) / Width, (LocalSize.Y - 2.0 * Margin) / Height), 0.001);
	OutOffset = FVector2D(0.5 * (LocalSize.X - Width * OutScale), 0.5 * (LocalSize.Y - Height * OutScale));
}

FVector2D SCameraMatchCanvas::ImageToLocal(double X, double Y) const
{
	return FVector2D(ViewOffset.X + X * ViewScale, ViewOffset.Y + Y * ViewScale);
}

void SCameraMatchCanvas::Tick(const FGeometry& AllottedGeometry, const double InCurrentTime, const float InDeltaTime)
{
	SLeafWidget::Tick(AllottedGeometry, InCurrentTime, InDeltaTime);
	if (bFitPending && Document.IsValid() && Document->bHasImage)
	{
		const FVector2D Size = AllottedGeometry.GetLocalSize();
		if (Size.X > 1.0 && Size.Y > 1.0)
		{
			double Scale = 1.0;
			FVector2D Offset = FVector2D::ZeroVector;
			GetView(Size, Scale, Offset);
			ViewScale = Scale;
			ViewOffset = Offset;
			bFitPending = false;
		}
	}
}

int32 SCameraMatchCanvas::OnPaint(const FPaintArgs& Args, const FGeometry& AllottedGeometry, const FSlateRect& MyCullingRect,
	FSlateWindowElementList& OutDrawElements, int32 LayerId, const FWidgetStyle& InWidgetStyle, bool bParentEnabled) const
{
	using namespace CameraMatchCanvas;
	using CameraMatch::EHandle;
	using CameraMatch::FVec2;
	using CameraMatch::FVec3;
	using CameraMatch::HandleIndex;

	const FVector2D Size = AllottedGeometry.GetLocalSize();
	const FSlateBrush* White = FCoreStyle::Get().GetBrush("GenericWhiteBox");
	FSlateDrawElement::MakeBox(OutDrawElements, LayerId, AllottedGeometry.ToPaintGeometry(), White, ESlateDrawEffect::None,
		FLinearColor(0.015f, 0.015f, 0.015f, 1.f));

	if (!Document.IsValid() || !Document->bHasImage)
	{
		DrawLabel(OutDrawElements, LayerId + 1, AllottedGeometry, FVector2D(20.0, 20.0),
			TEXT("Load a photo: \"Load Image File...\" or \"Use Selected Texture\" on the left."), FLinearColor(0.85f, 0.85f, 0.85f));
		return LayerId + 3;
	}

	const FCameraMatchDocument& Doc = *Document;
	const CameraMatch::FInput& In = Doc.Input;
	const CameraMatch::FResult& Result = Doc.Result;
	const bool bTwoPoints = In.Mode == CameraMatch::ESolveMode::TwoVanishingPoints;

	double Scale = 1.0;
	FVector2D Offset = FVector2D::ZeroVector;
	GetView(Size, Scale, Offset);
	auto ToLocal = [Scale, Offset](const FVec2& P)
	{
		return FVector2D(Offset.X + P.X * Scale, Offset.Y + P.Y * Scale);
	};
	auto HandleAt = [&In](EHandle Handle) -> const FVec2&
	{
		return In.Handles[HandleIndex(Handle)];
	};
	const FVector2D ViewMin = FVector2D::ZeroVector;
	const FVector2D ViewMax = Size;

	const int32 PhotoLayer = LayerId + 1;
	const int32 GuideLayer = LayerId + 2;
	const int32 LineLayer = LayerId + 3;
	const int32 HandleLayer = LayerId + 5;
	const int32 TextLayer = LayerId + 7;
	const int32 LoupeLayer = LayerId + 9;

	// The photo.
	FSlateDrawElement::MakeBox(OutDrawElements, PhotoLayer,
		RectGeometry(AllottedGeometry, Offset, FVector2D(In.ImageWidth * Scale, In.ImageHeight * Scale)),
		&Doc.ImageBrush, ESlateDrawEffect::None, FLinearColor::White);

	const FLinearColor Color1 = AxisColor(CameraMatch::AxisIndex(In.Axis1));
	const FLinearColor Color2 = AxisColor(CameraMatch::AxisIndex(In.Axis2));
	const FLinearColor ReferenceColor = AxisColor(In.ReferenceAxis);
	const FLinearColor OriginColor(1.f, 0.95f, 0.55f);

	struct FControlLine
	{
		EHandle Start;
		FLinearColor Color;
	};
	TArray<FControlLine> Lines;
	Lines.Add({EHandle::VP1LineAStart, Color1});
	Lines.Add({EHandle::VP1LineBStart, Color1});
	if (bTwoPoints)
	{
		Lines.Add({EHandle::VP2LineAStart, Color2});
		Lines.Add({EHandle::VP2LineBStart, Color2});
	}
	auto LineEnd = [&In](EHandle Start) -> const FVec2&
	{
		return In.Handles[HandleIndex(Start) + 1];
	};

	// Guides from the solved camera: ground grid, axes, horizon, vanishing points.
	if (Result.bValid)
	{
		auto DrawWorld = [&](const FVec3& A, const FVec3& B, const FLinearColor& Color, float Thickness)
		{
			FVec2 PixelA;
			FVec2 PixelB;
			if (!CameraMatch::ProjectSegment(Result, A, B, PixelA, PixelB))
			{
				return;
			}
			FVector2D LocalA = ToLocal(PixelA);
			FVector2D LocalB = ToLocal(PixelB);
			if (ClipToView(LocalA, LocalB, ViewMin, ViewMax, false))
			{
				DrawLine(OutDrawElements, GuideLayer, AllottedGeometry, LocalA, LocalB, Color, Thickness);
			}
		};

		const double Spacing = Doc.GridSpacing > 0.0 ? Doc.GridSpacing : 100.0;
		if (Doc.bShowGrid)
		{
			const int32 Cells = FMath::Clamp(Doc.GridCells, 1, 200);
			const double Extent = Spacing * Cells;
			for (int32 Index = -Cells; Index <= Cells; ++Index)
			{
				const double At = Index * Spacing;
				const bool bCentre = Index == 0;
				DrawWorld(FVec3{-Extent, At, 0.0}, FVec3{Extent, At, 0.0}, bCentre ? AxisColor(0, 0.6f) : FLinearColor(1.f, 1.f, 1.f, 0.25f), bCentre ? 1.5f : 1.f);
				DrawWorld(FVec3{At, -Extent, 0.0}, FVec3{At, Extent, 0.0}, bCentre ? AxisColor(1, 0.6f) : FLinearColor(1.f, 1.f, 1.f, 0.25f), bCentre ? 1.5f : 1.f);
			}
		}

		const double AxisLength = 2.0 * Spacing;
		DrawWorld(FVec3{}, FVec3{AxisLength, 0.0, 0.0}, AxisColor(0), 3.f);
		DrawWorld(FVec3{}, FVec3{0.0, AxisLength, 0.0}, AxisColor(1), 3.f);
		DrawWorld(FVec3{}, FVec3{0.0, 0.0, AxisLength}, AxisColor(2), 3.f);

		if (Doc.bShowHorizon && Result.bHasHorizon)
		{
			// a*x + b*y + c = 0: the point closest to (0,0), and a second point along the line.
			const double A = Result.Horizon[0];
			const double B = Result.Horizon[1];
			const double C = Result.Horizon[2];
			const double NormSquared = A * A + B * B;
			const FVec2 Point0{-A * C / NormSquared, -B * C / NormSquared};
			const FVec2 Point1{Point0.X - B * 1000.0, Point0.Y + A * 1000.0};
			FVector2D LocalA = ToLocal(Point0);
			FVector2D LocalB = ToLocal(Point1);
			if (ClipToView(LocalA, LocalB, ViewMin, ViewMax, true))
			{
				DrawLine(OutDrawElements, GuideLayer, AllottedGeometry, LocalA, LocalB, FLinearColor(1.f, 0.82f, 0.2f, 0.9f), 1.5f);
				const FVector2D Left = LocalA.X < LocalB.X ? LocalA : LocalB;
				DrawLabel(OutDrawElements, TextLayer, AllottedGeometry,
					FVector2D(FMath::Clamp(Left.X + 8.0, 4.0, Size.X - 80.0), FMath::Clamp(Left.Y - 20.0, 4.0, Size.Y - 20.0)),
					TEXT("Horizon"), FLinearColor(1.f, 0.82f, 0.2f));
			}
		}

		for (int32 Index = 0; Index < 3; ++Index)
		{
			if (!Result.bVanishingPointFinite[Index])
			{
				continue;
			}
			const FVector2D Point = ToLocal(Result.VanishingPoints[Index]);
			if (Point.X > -50.0 && Point.Y > -50.0 && Point.X < Size.X + 50.0 && Point.Y < Size.Y + 50.0)
			{
				const FLinearColor Color = AxisColor(Result.VanishingPointAxis[Index]);
				DrawCircle(OutDrawElements, GuideLayer, AllottedGeometry, Point, 5.0, Color, 2.f);
				DrawLabel(OutDrawElements, TextLayer, AllottedGeometry, Point + FVector2D(8.0, -8.0), FString::Printf(TEXT("VP%d"), Index + 1), Color);
			}
		}
	}

	// The control lines run on across the view, so you can see where they meet.
	if (Doc.bShowExtendedLines)
	{
		for (const FControlLine& Line : Lines)
		{
			FVector2D A = ToLocal(HandleAt(Line.Start));
			FVector2D B = ToLocal(LineEnd(Line.Start));
			if (FVector2D::DistSquared(A, B) > 1e-6 && ClipToView(A, B, ViewMin, ViewMax, true))
			{
				DrawLine(OutDrawElements, GuideLayer, AllottedGeometry, A, B, Line.Color.CopyWithNewOpacity(0.45f), 1.f);
			}
		}
	}

	// Control segments.
	for (const FControlLine& Line : Lines)
	{
		DrawOutlinedLine(OutDrawElements, LineLayer, AllottedGeometry, ToLocal(HandleAt(Line.Start)), ToLocal(LineEnd(Line.Start)), Line.Color, 2.f);
	}
	if (!bTwoPoints)
	{
		// The horizon line points along axis 2: draw it as an arrow.
		const FVector2D A = ToLocal(HandleAt(EHandle::HorizonStart));
		const FVector2D B = ToLocal(HandleAt(EHandle::HorizonEnd));
		DrawOutlinedLine(OutDrawElements, LineLayer, AllottedGeometry, A, B, Color2, 2.f);
		const FVector2D Direction = (B - A).GetSafeNormal();
		const FVector2D Side(-Direction.Y, Direction.X);
		DrawOutlinedLine(OutDrawElements, LineLayer, AllottedGeometry, B, B - Direction * 14.0 + Side * 7.0, Color2, 2.f);
		DrawOutlinedLine(OutDrawElements, LineLayer, AllottedGeometry, B, B - Direction * 14.0 - Side * 7.0, Color2, 2.f);
	}
	const bool bReference = In.Scale == CameraMatch::EScaleMode::ReferenceLength;
	if (bReference)
	{
		const FVector2D A = ToLocal(HandleAt(EHandle::Origin));
		const FVector2D B = ToLocal(HandleAt(EHandle::ReferenceEnd));
		DrawOutlinedLine(OutDrawElements, LineLayer, AllottedGeometry, A, B, ReferenceColor, 2.5f);
		DrawLabel(OutDrawElements, TextLayer, AllottedGeometry, (A + B) * 0.5 + FVector2D(8.0, -8.0),
			FString::Printf(TEXT("%g cm"), In.ReferenceLength), ReferenceColor);
	}

	// Handles.
	for (int32 Index = 0; Index < CameraMatch::HandleCount; ++Index)
	{
		if (!Doc.IsHandleActive(Index))
		{
			continue;
		}
		FLinearColor Color = Color1;
		if (Index >= HandleIndex(EHandle::VP2LineAStart) && Index <= HandleIndex(EHandle::HorizonEnd))
		{
			Color = Color2;
		}
		else if (Index == HandleIndex(EHandle::Origin))
		{
			Color = OriginColor;
		}
		else if (Index == HandleIndex(EHandle::ReferenceEnd))
		{
			Color = ReferenceColor;
		}
		const bool bHot = Index == HoverHandle || Index == DragHandle;
		const double Radius = bHot ? HandleRadius + 2.0 : HandleRadius;
		const FVector2D Point = ToLocal(In.Handles[Index]);
		DrawCircle(OutDrawElements, HandleLayer, AllottedGeometry, Point, Radius, FLinearColor(0.f, 0.f, 0.f, 0.7f), 3.5f);
		DrawCircle(OutDrawElements, HandleLayer + 1, AllottedGeometry, Point, Radius, bHot ? FLinearColor::White : Color, 1.5f);
		FSlateDrawElement::MakeBox(OutDrawElements, HandleLayer + 1, RectGeometry(AllottedGeometry, Point - FVector2D(1.0, 1.0), FVector2D(2.0, 2.0)),
			White, ESlateDrawEffect::None, Color);
	}

	// Labels.
	DrawLabel(OutDrawElements, TextLayer, AllottedGeometry, ToLocal(HandleAt(EHandle::VP1LineAEnd)) + FVector2D(10.0, -22.0),
		TEXT("VP1 ") + AxisText(In.Axis1), Color1);
	if (bTwoPoints)
	{
		DrawLabel(OutDrawElements, TextLayer, AllottedGeometry, ToLocal(HandleAt(EHandle::VP2LineAEnd)) + FVector2D(10.0, -22.0),
			TEXT("VP2 ") + AxisText(In.Axis2), Color2);
	}
	else
	{
		DrawLabel(OutDrawElements, TextLayer, AllottedGeometry, ToLocal(HandleAt(EHandle::HorizonEnd)) + FVector2D(10.0, -22.0),
			TEXT("Horizon ") + AxisText(In.Axis2), Color2);
	}
	DrawLabel(OutDrawElements, TextLayer, AllottedGeometry, ToLocal(HandleAt(EHandle::Origin)) + FVector2D(10.0, 6.0), TEXT("Origin"), OriginColor);

	if (!Result.bValid && !Result.Error.empty())
	{
		// First sentence only; the side panel has the whole message.
		FString Message = FString(UTF8_TO_TCHAR(Result.Error.c_str()));
		int32 Stop = INDEX_NONE;
		if (Message.FindChar(TEXT('.'), Stop))
		{
			Message.LeftInline(Stop + 1);
		}
		FSlateDrawElement::MakeBox(OutDrawElements, TextLayer, RectGeometry(AllottedGeometry, FVector2D::ZeroVector, FVector2D(Size.X, 26.0)),
			White, ESlateDrawEffect::None, FLinearColor(0.3f, 0.f, 0.f, 0.8f));
		DrawLabel(OutDrawElements, TextLayer + 1, AllottedGeometry, FVector2D(8.0, 5.0), Message, FLinearColor(1.f, 0.7f, 0.7f));
	}

	DrawLabel(OutDrawElements, TextLayer, AllottedGeometry, FVector2D(8.0, Size.Y - 22.0),
		TEXT("Drag handles (Shift = fine)   Wheel = zoom   Right/middle drag = pan   F = fit"), FLinearColor(0.8f, 0.8f, 0.8f, 0.8f));

	// Magnifier while dragging a handle.
	if (DragHandle != INDEX_NONE && Doc.IsHandleActive(DragHandle))
	{
		const FVec2& Handle = In.Handles[DragHandle];
		const double Region = FMath::Max(LoupeSize / (Scale * LoupeZoom), 8.0);
		if (Region < In.ImageWidth && Region < In.ImageHeight)
		{
			const double MinX = FMath::Clamp(Handle.X - 0.5 * Region, 0.0, In.ImageWidth - Region);
			const double MinY = FMath::Clamp(Handle.Y - 0.5 * Region, 0.0, In.ImageHeight - Region);
			const FVector2D HandleLocal = ToLocal(Handle);
			const FVector2D Position(HandleLocal.X < 0.5 * Size.X ? Size.X - LoupeSize - 12.0 : 12.0, 12.0);

			LoupeBrush = Doc.ImageBrush;
			LoupeBrush.SetUVRegion(FUVBox(
				FUVVector(static_cast<FUVScalar>(MinX / In.ImageWidth), static_cast<FUVScalar>(MinY / In.ImageHeight)),
				FUVVector(static_cast<FUVScalar>((MinX + Region) / In.ImageWidth), static_cast<FUVScalar>((MinY + Region) / In.ImageHeight))));

			FSlateDrawElement::MakeBox(OutDrawElements, LoupeLayer,
				RectGeometry(AllottedGeometry, Position - FVector2D(2.0, 2.0), FVector2D(LoupeSize + 4.0, LoupeSize + 4.0)),
				White, ESlateDrawEffect::None, FLinearColor(0.f, 0.f, 0.f, 1.f));
			FSlateDrawElement::MakeBox(OutDrawElements, LoupeLayer + 1,
				RectGeometry(AllottedGeometry, Position, FVector2D(LoupeSize, LoupeSize)), &LoupeBrush, ESlateDrawEffect::None, FLinearColor::White);

			auto ToLoupe = [&](const FVec2& P)
			{
				return Position + FVector2D((P.X - MinX) / Region * LoupeSize, (P.Y - MinY) / Region * LoupeSize);
			};
			const FGeometry LoupeGeometry = AllottedGeometry.MakeChild(ToSlate(FVector2D(LoupeSize, LoupeSize)), FSlateLayoutTransform(ToSlate(Position)));
			OutDrawElements.PushClip(FSlateClippingZone(LoupeGeometry));
			for (const FControlLine& Line : Lines)
			{
				DrawLine(OutDrawElements, LoupeLayer + 2, AllottedGeometry, ToLoupe(HandleAt(Line.Start)), ToLoupe(LineEnd(Line.Start)), Line.Color, 1.5f);
			}
			if (!bTwoPoints)
			{
				DrawLine(OutDrawElements, LoupeLayer + 2, AllottedGeometry, ToLoupe(HandleAt(EHandle::HorizonStart)), ToLoupe(HandleAt(EHandle::HorizonEnd)), Color2, 1.5f);
			}
			if (bReference)
			{
				DrawLine(OutDrawElements, LoupeLayer + 2, AllottedGeometry, ToLoupe(HandleAt(EHandle::Origin)), ToLoupe(HandleAt(EHandle::ReferenceEnd)), ReferenceColor, 1.5f);
			}
			const FVector2D Cross = ToLoupe(Handle);
			DrawLine(OutDrawElements, LoupeLayer + 3, AllottedGeometry, Cross - FVector2D(12.0, 0.0), Cross + FVector2D(12.0, 0.0), FLinearColor::White, 1.f);
			DrawLine(OutDrawElements, LoupeLayer + 3, AllottedGeometry, Cross - FVector2D(0.0, 12.0), Cross + FVector2D(0.0, 12.0), FLinearColor::White, 1.f);
			OutDrawElements.PopClip();
		}
	}

	return LoupeLayer + 4;
}

int32 SCameraMatchCanvas::FindHandleAt(const FVector2D& Local) const
{
	if (!Document.IsValid() || !Document->bHasImage)
	{
		return INDEX_NONE;
	}
	int32 Best = INDEX_NONE;
	double BestDistance = CameraMatchCanvas::HitRadius;
	for (int32 Index = 0; Index < CameraMatch::HandleCount; ++Index)
	{
		if (!Document->IsHandleActive(Index))
		{
			continue;
		}
		const CameraMatch::FVec2& P = Document->Input.Handles[Index];
		const double Distance = FVector2D::Distance(ImageToLocal(P.X, P.Y), Local);
		// <= so later handles (origin, reference) win, as they are drawn on top.
		if (Distance <= BestDistance)
		{
			Best = Index;
			BestDistance = Distance;
		}
	}
	return Best;
}

FReply SCameraMatchCanvas::OnMouseButtonDown(const FGeometry& MyGeometry, const FPointerEvent& MouseEvent)
{
	const FVector2D Local = MyGeometry.AbsoluteToLocal(MouseEvent.GetScreenSpacePosition());
	LastMouseLocal = Local;
	const FKey Button = MouseEvent.GetEffectingButton();

	if (Button == EKeys::LeftMouseButton && Document.IsValid() && Document->bHasImage)
	{
		DragHandle = FindHandleAt(Local);
		bPanning = DragHandle == INDEX_NONE;
		if (DragHandle != INDEX_NONE)
		{
			OnDragStarted.ExecuteIfBound();
		}
		Invalidate(EInvalidateWidgetReason::Paint);
		return FReply::Handled().CaptureMouse(SharedThis(this)).SetUserFocus(SharedThis(this), EFocusCause::Mouse);
	}
	if (Button == EKeys::RightMouseButton || Button == EKeys::MiddleMouseButton)
	{
		bPanning = true;
		return FReply::Handled().CaptureMouse(SharedThis(this)).SetUserFocus(SharedThis(this), EFocusCause::Mouse);
	}
	return FReply::Unhandled();
}

FReply SCameraMatchCanvas::OnMouseButtonUp(const FGeometry& MyGeometry, const FPointerEvent& MouseEvent)
{
	if (DragHandle != INDEX_NONE || bPanning)
	{
		EndDrag();
		return FReply::Handled().ReleaseMouseCapture();
	}
	return FReply::Unhandled();
}

FReply SCameraMatchCanvas::OnMouseMove(const FGeometry& MyGeometry, const FPointerEvent& MouseEvent)
{
	const FVector2D Local = MyGeometry.AbsoluteToLocal(MouseEvent.GetScreenSpacePosition());
	const FVector2D Delta = Local - LastMouseLocal;
	LastMouseLocal = Local;

	if (DragHandle != INDEX_NONE && HasMouseCapture() && Document.IsValid())
	{
		const double Factor = (MouseEvent.IsShiftDown() ? 0.2 : 1.0) / ViewScale;
		CameraMatch::FVec2& Handle = Document->Input.Handles[DragHandle];
		Handle.X = FMath::Clamp(Handle.X + Delta.X * Factor, 0.0, Document->Input.ImageWidth);
		Handle.Y = FMath::Clamp(Handle.Y + Delta.Y * Factor, 0.0, Document->Input.ImageHeight);
		OnHandlesChanged.ExecuteIfBound();
		Invalidate(EInvalidateWidgetReason::Paint);
		return FReply::Handled();
	}
	if (bPanning && HasMouseCapture())
	{
		ViewOffset += Delta;
		bFitPending = false;
		Invalidate(EInvalidateWidgetReason::Paint);
		return FReply::Handled();
	}

	const int32 Hover = FindHandleAt(Local);
	if (Hover != HoverHandle)
	{
		HoverHandle = Hover;
		Invalidate(EInvalidateWidgetReason::Paint);
	}
	return FReply::Unhandled();
}

FReply SCameraMatchCanvas::OnMouseWheel(const FGeometry& MyGeometry, const FPointerEvent& MouseEvent)
{
	if (!Document.IsValid() || !Document->bHasImage)
	{
		return FReply::Unhandled();
	}
	const FVector2D Local = MyGeometry.AbsoluteToLocal(MouseEvent.GetScreenSpacePosition());
	const FVector2D ImagePoint = (Local - ViewOffset) / ViewScale;
	ViewScale = FMath::Clamp(ViewScale * FMath::Pow(1.15, static_cast<double>(MouseEvent.GetWheelDelta())), 0.005, 64.0);
	ViewOffset = Local - ImagePoint * ViewScale;
	bFitPending = false;
	Invalidate(EInvalidateWidgetReason::Paint);
	return FReply::Handled();
}

void SCameraMatchCanvas::OnMouseLeave(const FPointerEvent& MouseEvent)
{
	SLeafWidget::OnMouseLeave(MouseEvent);
	if (HoverHandle != INDEX_NONE)
	{
		HoverHandle = INDEX_NONE;
		Invalidate(EInvalidateWidgetReason::Paint);
	}
}

void SCameraMatchCanvas::OnMouseCaptureLost(const FCaptureLostEvent& CaptureLostEvent)
{
	SLeafWidget::OnMouseCaptureLost(CaptureLostEvent);
	EndDrag();
}

void SCameraMatchCanvas::EndDrag()
{
	const bool bWasDragging = DragHandle != INDEX_NONE;
	DragHandle = INDEX_NONE;
	bPanning = false;
	if (bWasDragging)
	{
		OnDragFinished.ExecuteIfBound();
	}
	Invalidate(EInvalidateWidgetReason::Paint);
}

FReply SCameraMatchCanvas::OnKeyDown(const FGeometry& MyGeometry, const FKeyEvent& InKeyEvent)
{
	if (InKeyEvent.GetKey() == EKeys::F)
	{
		RequestFit();
		return FReply::Handled();
	}
	return FReply::Unhandled();
}

FCursorReply SCameraMatchCanvas::OnCursorQuery(const FGeometry& MyGeometry, const FPointerEvent& CursorEvent) const
{
	if (bPanning)
	{
		return FCursorReply::Cursor(EMouseCursor::GrabHandClosed);
	}
	if (DragHandle != INDEX_NONE)
	{
		return FCursorReply::Cursor(EMouseCursor::Crosshairs);
	}
	if (HoverHandle != INDEX_NONE)
	{
		return FCursorReply::Cursor(EMouseCursor::CardinalCross);
	}
	return FCursorReply::Unhandled();
}
