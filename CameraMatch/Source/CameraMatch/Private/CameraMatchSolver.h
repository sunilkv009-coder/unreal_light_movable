#pragma once

// Camera calibration from vanishing points (the fSpy method), with no Unreal
// dependencies so it can be unit tested outside the engine
// (tests/camera_match/solver_tests.cpp).
//
// Conventions
// - Image points are in pixels: (0,0) is the top-left corner, X right, Y down.
// - The principal point is the image centre.
// - World axes are Unreal's: X forward, Y right, Z up (left-handed), in cm.
// - The world origin is the point the user marks in the photo.

#include <string>
#include <vector>

namespace CameraMatch
{
	struct FVec2
	{
		double X = 0.0;
		double Y = 0.0;
	};

	struct FVec3
	{
		double X = 0.0;
		double Y = 0.0;
		double Z = 0.0;
	};

	enum class ESolveMode : int
	{
		/** One vanishing point plus the horizon direction. Needs the focal length. */
		OneVanishingPoint = 0,
		/** Two vanishing points of perpendicular directions. Computes the focal length. */
		TwoVanishingPoints = 1,
	};

	/** A signed world axis. For a vanishing point it is the direction that points towards that vanishing point. */
	enum class EWorldAxis : int
	{
		PosX = 0,
		NegX,
		PosY,
		NegY,
		PosZ,
		NegZ,
	};

	enum class EScaleMode : int
	{
		/** Camera is CameraDistance cm away from the origin. */
		CameraDistance = 0,
		/** Camera is CameraHeight cm above the ground (Z = 0) the origin sits on. */
		CameraHeight,
		/** The segment from the origin to the reference handle, along ReferenceAxis, is ReferenceLength cm long. */
		ReferenceLength,
	};

	/** The draggable control points. */
	enum class EHandle : int
	{
		VP1LineAStart = 0,
		VP1LineAEnd,
		VP1LineBStart,
		VP1LineBEnd,
		VP2LineAStart,
		VP2LineAEnd,
		VP2LineBStart,
		VP2LineBEnd,
		HorizonStart,
		HorizonEnd,
		Origin,
		ReferenceEnd,
	};

	constexpr int HandleCount = 12;

	inline int HandleIndex(EHandle Handle)
	{
		return static_cast<int>(Handle);
	}

	struct FInput
	{
		double ImageWidth = 0.0;
		double ImageHeight = 0.0;

		ESolveMode Mode = ESolveMode::TwoVanishingPoints;

		/** Direction towards vanishing point 1. */
		EWorldAxis Axis1 = EWorldAxis::PosX;
		/** Two VPs: direction towards vanishing point 2. One VP: direction of the horizon line, from its start to its end. */
		EWorldAxis Axis2 = EWorldAxis::PosY;

		/** Sensor size along the image's longer side, in mm (36 for full frame). */
		double SensorMM = 36.0;
		/** One VP mode only: the lens focal length in mm. */
		double FocalMM = 35.0;

		EScaleMode Scale = EScaleMode::CameraDistance;
		double CameraDistance = 1000.0;
		double CameraHeight = 160.0;
		/** 0 = X, 1 = Y, 2 = Z. The sign comes from which side of the origin the handle is. */
		int ReferenceAxis = 0;
		double ReferenceLength = 100.0;

		FVec2 Handles[HandleCount];
	};

	struct FResult
	{
		bool bValid = false;
		std::string Error;
		std::vector<std::string> Warnings;

		/** Focal length in pixels, and relative to half the image's longer side. */
		double FocalPixels = 0.0;
		double FocalRelative = 0.0;
		double FocalMM = 0.0;
		double SensorWidthMM = 0.0;
		double SensorHeightMM = 0.0;
		double HorizontalFovDeg = 0.0;
		double VerticalFovDeg = 0.0;

		FVec2 PrincipalPoint;

		/** VP1, VP2 and the third, computed one, in pixels. Not finite when that axis is parallel to the image. */
		FVec2 VanishingPoints[3];
		bool bVanishingPointFinite[3] = {false, false, false};
		/** World axis (0 X, 1 Y, 2 Z) of each vanishing point above. */
		int VanishingPointAxis[3] = {0, 1, 2};

		/** World-to-camera rotation. The camera frame is X right, Y down, Z forward (into the photo). */
		double WorldToCamera[3][3] = {{1, 0, 0}, {0, 1, 0}, {0, 0, 1}};

		/** Camera position (cm) and orientation in Unreal's world. */
		FVec3 Location;
		FVec3 Forward;
		FVec3 Right;
		FVec3 Up;
		/** Unreal FRotator angles, degrees. */
		double Pitch = 0.0;
		double Yaw = 0.0;
		double Roll = 0.0;

		double DistanceToOrigin = 0.0;

		/** The reference handle moved onto the image of its axis line (pixels). */
		FVec2 ReferenceEndOnAxis;

		/** Horizon of the ground plane (Z = 0) as a*x + b*y + c = 0 in pixels. */
		bool bHasHorizon = false;
		double Horizon[3] = {0.0, 0.0, 0.0};
	};

	FResult Solve(const FInput& Input);

	/** Puts the handles in a default layout for Input.Mode and the image size. */
	void ResetHandles(FInput& Input);

	/** Projects a world point (cm) to pixels. False if it is behind the camera. */
	bool ProjectPoint(const FResult& Result, const FVec3& World, FVec2& OutPixel);

	/** Projects a world segment, clipped at the camera's near plane. False if it is entirely behind the camera. */
	bool ProjectSegment(const FResult& Result, const FVec3& A, const FVec3& B, FVec2& OutA, FVec2& OutB);

	/** 0 = X, 1 = Y, 2 = Z. */
	int AxisIndex(EWorldAxis Axis);
	double AxisSign(EWorldAxis Axis);
	const char* AxisLabel(EWorldAxis Axis);

	/** Unreal's FMatrix::Rotator() for a rotation with these X (forward), Y (right) and Z (up) axes. */
	void RotatorFromAxes(const FVec3& Forward, const FVec3& Right, const FVec3& Up, double& OutPitch, double& OutYaw, double& OutRoll);
}
