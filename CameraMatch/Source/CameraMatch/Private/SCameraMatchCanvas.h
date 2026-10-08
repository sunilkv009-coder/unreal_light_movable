#pragma once

#include "CoreMinimal.h"
#include "Input/Reply.h"
#include "Styling/SlateBrush.h"
#include "Widgets/DeclarativeSyntaxSupport.h"
#include "Widgets/SLeafWidget.h"

struct FCameraMatchDocument;

/**
 * The photo with the control lines on top, like fSpy's main view.
 *
 * Left-drag a handle to move it (Shift for fine control). Wheel zooms, right/middle drag
 * or left drag on empty space pans, F fits the photo. When the solve is valid it also
 * draws the ground grid, the world axes at the origin and the horizon, projected with
 * the solved camera, so you can see whether the camera matches.
 */
class SCameraMatchCanvas : public SLeafWidget
{
public:
	SLATE_BEGIN_ARGS(SCameraMatchCanvas) {}
		SLATE_ARGUMENT(TSharedPtr<FCameraMatchDocument>, Document)
		/** A handle moved. */
		SLATE_EVENT(FSimpleDelegate, OnHandlesChanged)
		SLATE_EVENT(FSimpleDelegate, OnDragStarted)
		SLATE_EVENT(FSimpleDelegate, OnDragFinished)
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs);

	/** Fit the whole photo into the view. */
	void RequestFit();

	virtual int32 OnPaint(const FPaintArgs& Args, const FGeometry& AllottedGeometry, const FSlateRect& MyCullingRect,
		FSlateWindowElementList& OutDrawElements, int32 LayerId, const FWidgetStyle& InWidgetStyle, bool bParentEnabled) const override;
	virtual FVector2D ComputeDesiredSize(float LayoutScaleMultiplier) const override;
	virtual void Tick(const FGeometry& AllottedGeometry, const double InCurrentTime, const float InDeltaTime) override;

	virtual FReply OnMouseButtonDown(const FGeometry& MyGeometry, const FPointerEvent& MouseEvent) override;
	virtual FReply OnMouseButtonUp(const FGeometry& MyGeometry, const FPointerEvent& MouseEvent) override;
	virtual FReply OnMouseMove(const FGeometry& MyGeometry, const FPointerEvent& MouseEvent) override;
	virtual FReply OnMouseWheel(const FGeometry& MyGeometry, const FPointerEvent& MouseEvent) override;
	virtual void OnMouseLeave(const FPointerEvent& MouseEvent) override;
	virtual void OnMouseCaptureLost(const FCaptureLostEvent& CaptureLostEvent) override;
	virtual FReply OnKeyDown(const FGeometry& MyGeometry, const FKeyEvent& InKeyEvent) override;
	virtual bool SupportsKeyboardFocus() const override { return true; }
	virtual FCursorReply OnCursorQuery(const FGeometry& MyGeometry, const FPointerEvent& CursorEvent) const override;

private:
	/** View scale (local units per image pixel) and offset (local position of image pixel 0,0). */
	void GetView(const FVector2D& LocalSize, double& OutScale, FVector2D& OutOffset) const;
	FVector2D ImageToLocal(double X, double Y) const;
	int32 FindHandleAt(const FVector2D& Local) const;
	void EndDrag();

	TSharedPtr<FCameraMatchDocument> Document;
	FSimpleDelegate OnHandlesChanged;
	FSimpleDelegate OnDragStarted;
	FSimpleDelegate OnDragFinished;

	double ViewScale = 1.0;
	FVector2D ViewOffset = FVector2D::ZeroVector;
	bool bFitPending = true;

	int32 DragHandle = INDEX_NONE;
	int32 HoverHandle = INDEX_NONE;
	bool bPanning = false;
	FVector2D LastMouseLocal = FVector2D::ZeroVector;

	/** The magnifier's view of the photo. A member, so the draw element never points at a temporary. */
	mutable FSlateBrush LoupeBrush;
};
