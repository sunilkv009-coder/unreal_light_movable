#pragma once

#include "CoreMinimal.h"
#include "Styling/SlateBrush.h"

#include "CameraMatchSolver.h"

/** What the tab and the canvas share: the photo, the handles, the settings and the latest solve. */
struct FCameraMatchDocument
{
	CameraMatch::FInput Input;
	CameraMatch::FResult Result;

	/** Draws the photo. The tab keeps its texture alive. */
	FSlateBrush ImageBrush;
	bool bHasImage = false;

	bool bShowGrid = true;
	bool bShowHorizon = true;
	bool bShowExtendedLines = true;
	/** Ground grid cell size in cm, and number of cells each side of the origin. */
	double GridSpacing = 100.0;
	int32 GridCells = 10;

	/** Whether a handle is used by the current method and scale mode. */
	bool IsHandleActive(int32 Index) const
	{
		using CameraMatch::EHandle;
		using CameraMatch::HandleIndex;
		if (Index <= HandleIndex(EHandle::VP1LineBEnd))
		{
			return true;
		}
		if (Index <= HandleIndex(EHandle::VP2LineBEnd))
		{
			return Input.Mode == CameraMatch::ESolveMode::TwoVanishingPoints;
		}
		if (Index <= HandleIndex(EHandle::HorizonEnd))
		{
			return Input.Mode == CameraMatch::ESolveMode::OneVanishingPoint;
		}
		if (Index == HandleIndex(EHandle::Origin))
		{
			return true;
		}
		return Index == HandleIndex(EHandle::ReferenceEnd) && Input.Scale == CameraMatch::EScaleMode::ReferenceLength;
	}

	void Solve()
	{
		Result = CameraMatch::Solve(Input);
		if (Result.bValid && Input.Scale == CameraMatch::EScaleMode::ReferenceLength)
		{
			// Keep the reference handle on its axis line.
			Input.Handles[CameraMatch::HandleIndex(CameraMatch::EHandle::ReferenceEnd)] = Result.ReferenceEndOnAxis;
		}
	}
};
