#include "CameraMatchSolver.h"

#include <cmath>
#include <cstdio>

namespace CameraMatch
{
	namespace SolverMath
	{
		constexpr double Pi = 3.14159265358979323846;

		/** Vanishing points further than this (in half image widths) count as "lines are parallel". */
		constexpr double MaxVanishingDistance = 1.0e5;

		/** Beyond this the focal length depends heavily on tiny changes of the lines. */
		constexpr double FarVanishingDistance = 20.0;

		inline double Degrees(double Radians)
		{
			return Radians * 180.0 / Pi;
		}

		inline double Larger(double A, double B)
		{
			return A > B ? A : B;
		}

		inline FVec3 Add(const FVec3& A, const FVec3& B)
		{
			return FVec3{A.X + B.X, A.Y + B.Y, A.Z + B.Z};
		}

		inline FVec3 Sub(const FVec3& A, const FVec3& B)
		{
			return FVec3{A.X - B.X, A.Y - B.Y, A.Z - B.Z};
		}

		inline FVec3 Mul(const FVec3& A, double S)
		{
			return FVec3{A.X * S, A.Y * S, A.Z * S};
		}

		inline double Dot(const FVec3& A, const FVec3& B)
		{
			return A.X * B.X + A.Y * B.Y + A.Z * B.Z;
		}

		inline FVec3 Cross(const FVec3& A, const FVec3& B)
		{
			return FVec3{A.Y * B.Z - A.Z * B.Y, A.Z * B.X - A.X * B.Z, A.X * B.Y - A.Y * B.X};
		}

		inline double Length(const FVec3& A)
		{
			return std::sqrt(Dot(A, A));
		}

		inline FVec3 Normalized(const FVec3& A)
		{
			const double L = Length(A);
			return L > 0.0 ? Mul(A, 1.0 / L) : A;
		}

		inline double Component(const FVec3& A, int Index)
		{
			return Index == 0 ? A.X : (Index == 1 ? A.Y : A.Z);
		}

		inline FVec3 Row(const double M[3][3], int Index)
		{
			return FVec3{M[Index][0], M[Index][1], M[Index][2]};
		}

		inline FVec3 ToCamera(const FResult& Result, const FVec3& World)
		{
			const FVec3 D = Sub(World, Result.Location);
			return FVec3{Dot(Row(Result.WorldToCamera, 0), D), Dot(Row(Result.WorldToCamera, 1), D), Dot(Row(Result.WorldToCamera, 2), D)};
		}

		inline bool ProjectCamera(const FResult& Result, const FVec3& Camera, FVec2& OutPixel)
		{
			if (Camera.Z <= 1e-9)
			{
				return false;
			}
			OutPixel.X = Result.PrincipalPoint.X + Result.FocalPixels * Camera.X / Camera.Z;
			OutPixel.Y = Result.PrincipalPoint.Y + Result.FocalPixels * Camera.Y / Camera.Z;
			return true;
		}

		FResult& Fail(FResult& Result, const std::string& Message)
		{
			Result.bValid = false;
			Result.Error = Message;
			return Result;
		}

		/**
		 * Intersects two image lines given by two points each (normalized coordinates).
		 * Fails if a line has no length or the lines are parallel.
		 */
		bool VanishingPoint(const FVec2& A0, const FVec2& A1, const FVec2& B0, const FVec2& B1, const char* Name, FVec2& OutPoint, std::string& OutError)
		{
			const FVec3 LineA = Cross(FVec3{A0.X, A0.Y, 1.0}, FVec3{A1.X, A1.Y, 1.0});
			const FVec3 LineB = Cross(FVec3{B0.X, B0.Y, 1.0}, FVec3{B1.X, B1.Y, 1.0});
			if (std::hypot(LineA.X, LineA.Y) < 1e-4 || std::hypot(LineB.X, LineB.Y) < 1e-4)
			{
				OutError = std::string("A line of ") + Name + " has no length. Drag its two ends apart.";
				return false;
			}

			const FVec3 Point = Cross(LineA, LineB);
			const double Planar = std::hypot(Point.X, Point.Y);
			if (std::fabs(Point.Z) < 1e-12 || Planar / std::fabs(Point.Z) > MaxVanishingDistance)
			{
				OutError = std::string("The two lines of ") + Name
					+ " are parallel in the photo, so they don't meet. Edges that are parallel in the real world"
					  " converge in a photo: follow them more closely, or use edges further apart.";
				return false;
			}

			OutPoint = FVec2{Point.X / Point.Z, Point.Y / Point.Z};
			return true;
		}
	}

	int AxisIndex(EWorldAxis Axis)
	{
		return static_cast<int>(Axis) / 2;
	}

	double AxisSign(EWorldAxis Axis)
	{
		return (static_cast<int>(Axis) % 2) == 0 ? 1.0 : -1.0;
	}

	const char* AxisLabel(EWorldAxis Axis)
	{
		static const char* const Labels[6] = {"+X", "-X", "+Y", "-Y", "+Z", "-Z"};
		const int Index = static_cast<int>(Axis);
		return (Index >= 0 && Index < 6) ? Labels[Index] : "?";
	}

	void RotatorFromAxes(const FVec3& Forward, const FVec3& Right, const FVec3& Up, double& OutPitch, double& OutYaw, double& OutRoll)
	{
		using namespace SolverMath;

		// Same steps as Unreal's FMatrix::Rotator().
		const double YawRadians = std::atan2(Forward.Y, Forward.X);
		OutPitch = Degrees(std::atan2(Forward.Z, std::sqrt(Forward.X * Forward.X + Forward.Y * Forward.Y)));
		OutYaw = Degrees(YawRadians);

		const FVec3 NoRollRight{-std::sin(YawRadians), std::cos(YawRadians), 0.0};
		OutRoll = Degrees(std::atan2(Dot(Up, NoRollRight), Dot(Right, NoRollRight)));
	}

	FResult Solve(const FInput& Input)
	{
		using namespace SolverMath;

		FResult Result;
		const double Width = Input.ImageWidth;
		const double Height = Input.ImageHeight;
		if (!(Width > 0.0 && Height > 0.0))
		{
			return Fail(Result, "Load a photo first.");
		}

		// Work in normalized coordinates: principal point at 0, half the longer side = 1.
		const double HalfSize = 0.5 * Larger(Width, Height);
		const FVec2 Centre{0.5 * Width, 0.5 * Height};
		Result.PrincipalPoint = Centre;

		auto ToNormalized = [&Input, &Centre, HalfSize](EHandle Handle)
		{
			const FVec2& P = Input.Handles[HandleIndex(Handle)];
			return FVec2{(P.X - Centre.X) / HalfSize, (P.Y - Centre.Y) / HalfSize};
		};
		auto ToPixels = [&Centre, HalfSize](const FVec2& P)
		{
			return FVec2{Centre.X + P.X * HalfSize, Centre.Y + P.Y * HalfSize};
		};

		const bool bTwoPoints = Input.Mode == ESolveMode::TwoVanishingPoints;
		const int Axis1 = AxisIndex(Input.Axis1);
		const int Axis2 = AxisIndex(Input.Axis2);
		if (Axis1 == Axis2)
		{
			return Fail(Result, bTwoPoints
				? "Vanishing point 1 and vanishing point 2 must use different axes (for example X and Y)."
				: "The horizon line must use a different axis from vanishing point 1 (for example X and Y).");
		}

		FVec2 Point1;
		if (!VanishingPoint(ToNormalized(EHandle::VP1LineAStart), ToNormalized(EHandle::VP1LineAEnd),
				ToNormalized(EHandle::VP1LineBStart), ToNormalized(EHandle::VP1LineBEnd), "vanishing point 1", Point1, Result.Error))
		{
			return Result;
		}
		Result.VanishingPoints[0] = ToPixels(Point1);
		Result.bVanishingPointFinite[0] = true;

		// Camera-frame directions (X right, Y down, Z forward) towards vanishing point 1 and 2.
		double Focal = 0.0;
		FVec3 Direction1;
		FVec3 Direction2;
		if (bTwoPoints)
		{
			FVec2 Point2;
			if (!VanishingPoint(ToNormalized(EHandle::VP2LineAStart), ToNormalized(EHandle::VP2LineAEnd),
					ToNormalized(EHandle::VP2LineBStart), ToNormalized(EHandle::VP2LineBEnd), "vanishing point 2", Point2, Result.Error))
			{
				return Result;
			}
			Result.VanishingPoints[1] = ToPixels(Point2);
			Result.bVanishingPointFinite[1] = true;

			// Rays to the two vanishing points must be perpendicular: P1.P2 + f^2 = 0.
			const double FocalSquared = -(Point1.X * Point2.X + Point1.Y * Point2.Y);
			if (FocalSquared <= 1e-6)
			{
				return Fail(Result,
					"These two vanishing points can't come from a real camera, so no focal length fits."
					" The vanishing points of two perpendicular directions are on opposite sides of the photo's centre."
					" Check that each pair of lines follows edges that are parallel in the real world,"
					" and that the two directions are at 90 degrees to each other.");
			}
			Focal = std::sqrt(FocalSquared);
			Direction1 = Normalized(FVec3{Point1.X, Point1.Y, Focal});
			Direction2 = Normalized(FVec3{Point2.X, Point2.Y, Focal});

			for (int Index = 0; Index < 2; ++Index)
			{
				const FVec2& P = Index == 0 ? Point1 : Point2;
				if (std::hypot(P.X, P.Y) > FarVanishingDistance)
				{
					char Buffer[256];
					std::snprintf(Buffer, sizeof(Buffer),
						"Vanishing point %d is very far outside the photo, so the focal length changes a lot with small"
						" changes of its lines. Lines that converge more clearly give a better result.", Index + 1);
					Result.Warnings.push_back(Buffer);
				}
			}
		}
		else
		{
			if (!(Input.SensorMM > 0.0) || !(Input.FocalMM > 0.0))
			{
				return Fail(Result, "Enter the focal length and sensor size (both more than 0).");
			}
			Focal = 2.0 * Input.FocalMM / Input.SensorMM;
			Direction1 = Normalized(FVec3{Point1.X, Point1.Y, Focal});

			// The horizon line through vanishing point 1 back-projects to the plane of axis 1 and axis 2.
			// Axis 2 is the direction in that plane perpendicular to axis 1, pointing from the line's start to its end.
			const FVec2 HorizonStart = ToNormalized(EHandle::HorizonStart);
			const FVec2 HorizonEnd = ToNormalized(EHandle::HorizonEnd);
			const FVec3 HorizonDirection{HorizonEnd.X - HorizonStart.X, HorizonEnd.Y - HorizonStart.Y, 0.0};
			if (Length(HorizonDirection) < 1e-4)
			{
				return Fail(Result, "The horizon line has no length. Drag its two ends apart.");
			}
			const FVec3 Unit = Normalized(HorizonDirection);
			const FVec3 Perpendicular = Sub(Unit, Mul(Direction1, Dot(Unit, Direction1)));
			if (Length(Perpendicular) < 1e-6)
			{
				return Fail(Result, "The horizon line points straight at vanishing point 1. Turn it to follow the horizon.");
			}
			Direction2 = Normalized(Perpendicular);
		}

		// Columns of the world-to-camera rotation: where each world axis points in the camera frame.
		FVec3 Columns[3];
		Columns[Axis1] = Mul(Direction1, AxisSign(Input.Axis1));
		Columns[Axis2] = Mul(Direction2, AxisSign(Input.Axis2));
		const int Axis3 = 3 - Axis1 - Axis2;
		// Unreal's world is left-handed and the camera frame is right-handed, so X x Y = -Z here.
		const bool bCyclic = Axis2 == (Axis1 + 1) % 3;
		Columns[Axis3] = Mul(Cross(Columns[Axis1], Columns[Axis2]), bCyclic ? -1.0 : 1.0);

		for (int RowIndex = 0; RowIndex < 3; ++RowIndex)
		{
			for (int Column = 0; Column < 3; ++Column)
			{
				Result.WorldToCamera[RowIndex][Column] = Component(Columns[Column], RowIndex);
			}
		}

		auto VanishingPointOf = [&ToPixels, Focal](const FVec3& Direction, FVec2& OutPixel)
		{
			if (std::fabs(Direction.Z) < 1e-6)
			{
				return false;
			}
			OutPixel = ToPixels(FVec2{Focal * Direction.X / Direction.Z, Focal * Direction.Y / Direction.Z});
			return true;
		};
		Result.VanishingPointAxis[0] = Axis1;
		Result.VanishingPointAxis[1] = Axis2;
		Result.VanishingPointAxis[2] = Axis3;
		if (!bTwoPoints)
		{
			Result.bVanishingPointFinite[1] = VanishingPointOf(Columns[Axis2], Result.VanishingPoints[1]);
		}
		Result.bVanishingPointFinite[2] = VanishingPointOf(Columns[Axis3], Result.VanishingPoints[2]);

		// Camera axes in the world: the rows of the world-to-camera rotation.
		Result.Right = Row(Result.WorldToCamera, 0);
		Result.Up = Mul(Row(Result.WorldToCamera, 1), -1.0);
		Result.Forward = Row(Result.WorldToCamera, 2);
		RotatorFromAxes(Result.Forward, Result.Right, Result.Up, Result.Pitch, Result.Yaw, Result.Roll);

		// Distance from the camera to the origin, along the ray through the origin handle.
		const FVec2 Origin = ToNormalized(EHandle::Origin);
		const FVec3 OriginRay = Normalized(FVec3{Origin.X, Origin.Y, Focal});
		double Distance = 0.0;
		switch (Input.Scale)
		{
		case EScaleMode::CameraDistance:
			if (!(Input.CameraDistance > 0.0))
			{
				return Fail(Result, "The camera distance must be more than 0.");
			}
			Distance = Input.CameraDistance;
			break;

		case EScaleMode::CameraHeight:
		{
			if (!(Input.CameraHeight > 0.0))
			{
				return Fail(Result, "The camera height must be more than 0.");
			}
			const double UpAlongRay = Dot(Columns[2], OriginRay);
			if (UpAlongRay > -1e-6)
			{
				return Fail(Result,
					"The origin is on or above the horizon, so the camera can't be above it."
					" Put the origin on the ground, or use another scale option.");
			}
			Distance = -Input.CameraHeight / UpAlongRay;
			break;
		}

		case EScaleMode::ReferenceLength:
		{
			if (!(Input.ReferenceLength > 0.0))
			{
				return Fail(Result, "The reference length must be more than 0.");
			}
			const int ReferenceAxis = Input.ReferenceAxis < 0 ? 0 : (Input.ReferenceAxis > 2 ? 2 : Input.ReferenceAxis);
			const FVec3 AxisDirection = Columns[ReferenceAxis];

			// The axis line through the origin appears as the line from the origin to that axis's vanishing point.
			const FVec3 Line = Cross(FVec3{Origin.X, Origin.Y, 1.0},
				FVec3{Focal * AxisDirection.X, Focal * AxisDirection.Y, AxisDirection.Z});
			const double LineScale = Line.X * Line.X + Line.Y * Line.Y;
			if (LineScale < 1e-18)
			{
				return Fail(Result, "The origin is on the vanishing point of the reference axis. Move the origin, or pick another reference axis.");
			}
			const FVec2 Handle = ToNormalized(EHandle::ReferenceEnd);
			const double Offset = (Line.X * Handle.X + Line.Y * Handle.Y + Line.Z) / LineScale;
			const FVec2 OnAxis{Handle.X - Offset * Line.X, Handle.Y - Offset * Line.Y};
			Result.ReferenceEndOnAxis = ToPixels(OnAxis);

			// Origin at t * OriginRay, reference end at s * EndRay, and their difference is Length * axis:
			// t * OriginRay + Length * axis = s * EndRay. Solve for t and s.
			const FVec3 EndRay = Normalized(FVec3{OnAxis.X, OnAxis.Y, Focal});
			const double Cosine = Dot(OriginRay, EndRay);
			const double Denominator = 1.0 - Cosine * Cosine;
			if (Denominator < 1e-12)
			{
				return Fail(Result, "Drag the reference handle away from the origin.");
			}
			const double Alpha = Dot(OriginRay, AxisDirection);
			double Beta = Dot(EndRay, AxisDirection);
			double T = Input.ReferenceLength * (Cosine * Beta - Alpha) / Denominator;
			if (T < 0.0)
			{
				// The handle is on the negative side of the axis: measure along -axis instead.
				T = -T;
				Beta = -Beta;
			}
			const double S = T * Cosine + Input.ReferenceLength * Beta;
			if (!(T > 0.0) || !(S > 0.0))
			{
				return Fail(Result,
					"The reference handle is past the vanishing point of its axis, which would put it behind the camera."
					" Put it between the origin and that vanishing point, or on the other side of the origin.");
			}
			Distance = T;
			break;
		}
		}

		Result.DistanceToOrigin = Distance;
		Result.Location = FVec3{
			-Distance * Dot(Columns[0], OriginRay),
			-Distance * Dot(Columns[1], OriginRay),
			-Distance * Dot(Columns[2], OriginRay)};

		// Lens.
		Result.FocalRelative = Focal;
		Result.FocalPixels = Focal * HalfSize;
		Result.HorizontalFovDeg = Degrees(2.0 * std::atan(0.5 * Width / Result.FocalPixels));
		Result.VerticalFovDeg = Degrees(2.0 * std::atan(0.5 * Height / Result.FocalPixels));
		const double SensorMM = Input.SensorMM > 0.0 ? Input.SensorMM : 36.0;
		const double LongSide = Larger(Width, Height);
		Result.SensorWidthMM = SensorMM * Width / LongSide;
		Result.SensorHeightMM = SensorMM * Height / LongSide;
		Result.FocalMM = 0.5 * Focal * SensorMM;

		// Horizon of the ground plane: the image points whose rays are perpendicular to world up.
		const FVec3& UpInCamera = Columns[2];
		if (std::hypot(UpInCamera.X, UpInCamera.Y) > 1e-9)
		{
			Result.bHasHorizon = true;
			Result.Horizon[0] = UpInCamera.X;
			Result.Horizon[1] = UpInCamera.Y;
			Result.Horizon[2] = UpInCamera.Z * Result.FocalPixels - UpInCamera.X * Centre.X - UpInCamera.Y * Centre.Y;
		}

		if (Result.Up.Z < 0.0)
		{
			Result.Warnings.push_back(
				"The camera is upside down: world Z (up) points down in this photo."
				" Flip the sign of one axis (for example +X to -X).");
		}
		if (Result.HorizontalFovDeg > 120.0)
		{
			char Buffer[256];
			std::snprintf(Buffer, sizeof(Buffer),
				"Very wide field of view (%.0f degrees). Check the lines. Wide-angle photos should be undistorted first.",
				Result.HorizontalFovDeg);
			Result.Warnings.push_back(Buffer);
		}

		Result.bValid = true;
		return Result;
	}

	void ResetHandles(FInput& Input)
	{
		const double W = Input.ImageWidth;
		const double H = Input.ImageHeight;
		auto Set = [&Input, W, H](EHandle Handle, double X, double Y)
		{
			Input.Handles[HandleIndex(Handle)] = FVec2{X * W, Y * H};
		};

		if (Input.Mode == ESolveMode::TwoVanishingPoints)
		{
			// Two sets of lines converging left and right, like the two sides of a building corner.
			Set(EHandle::VP1LineAStart, 0.43, 0.75);
			Set(EHandle::VP1LineAEnd, 0.12, 0.62);
			Set(EHandle::VP1LineBStart, 0.43, 0.30);
			Set(EHandle::VP1LineBEnd, 0.12, 0.38);
			Set(EHandle::Origin, 0.50, 0.78);
			Set(EHandle::ReferenceEnd, 0.36, 0.74);
		}
		else
		{
			// Lines converging in the middle, like looking down a corridor.
			Set(EHandle::VP1LineAStart, 0.20, 0.85);
			Set(EHandle::VP1LineAEnd, 0.40, 0.60);
			Set(EHandle::VP1LineBStart, 0.80, 0.85);
			Set(EHandle::VP1LineBEnd, 0.60, 0.60);
			Set(EHandle::Origin, 0.50, 0.80);
			Set(EHandle::ReferenceEnd, 0.50, 0.68);
		}
		Set(EHandle::VP2LineAStart, 0.57, 0.75);
		Set(EHandle::VP2LineAEnd, 0.88, 0.62);
		Set(EHandle::VP2LineBStart, 0.57, 0.30);
		Set(EHandle::VP2LineBEnd, 0.88, 0.38);
		Set(EHandle::HorizonStart, 0.25, 0.45);
		Set(EHandle::HorizonEnd, 0.75, 0.45);
	}

	bool ProjectPoint(const FResult& Result, const FVec3& World, FVec2& OutPixel)
	{
		return SolverMath::ProjectCamera(Result, SolverMath::ToCamera(Result, World), OutPixel);
	}

	bool ProjectSegment(const FResult& Result, const FVec3& A, const FVec3& B, FVec2& OutA, FVec2& OutB)
	{
		using namespace SolverMath;

		FVec3 CameraA = ToCamera(Result, A);
		FVec3 CameraB = ToCamera(Result, B);
		const double Near = 1e-3 * Larger(Result.DistanceToOrigin, 1.0);
		if (CameraA.Z < Near && CameraB.Z < Near)
		{
			return false;
		}
		if (CameraA.Z < Near)
		{
			CameraA = Add(CameraA, Mul(Sub(CameraB, CameraA), (Near - CameraA.Z) / (CameraB.Z - CameraA.Z)));
		}
		else if (CameraB.Z < Near)
		{
			CameraB = Add(CameraB, Mul(Sub(CameraA, CameraB), (Near - CameraB.Z) / (CameraA.Z - CameraB.Z)));
		}
		return ProjectCamera(Result, CameraA, OutA) && ProjectCamera(Result, CameraB, OutB);
	}
}
