// Unit tests for CameraMatchSolver (no Unreal needed).
// Run: python3 tests/test_camera_match.py
//
// Each test places a known Unreal camera, projects real-world parallel edges into a
// synthetic photo using Unreal's own rotation and projection conventions, gives
// those lines to the solver, and checks it recovers the camera.

#include "CameraMatchSolver.h"

#include <cmath>
#include <cstdio>
#include <string>

using namespace CameraMatch;

namespace
{
	int Failures = 0;
	int Checks = 0;

	void Check(bool bCondition, const std::string& What)
	{
		++Checks;
		if (!bCondition)
		{
			++Failures;
			std::printf("  FAIL: %s\n", What.c_str());
		}
	}

	void CheckNear(double Actual, double Expected, double Tolerance, const std::string& What)
	{
		++Checks;
		if (!(std::fabs(Actual - Expected) <= Tolerance))
		{
			++Failures;
			std::printf("  FAIL: %s: got %.6f, expected %.6f (tolerance %g)\n", What.c_str(), Actual, Expected, Tolerance);
		}
	}

	constexpr double Pi = 3.14159265358979323846;

	double Radians(double Degrees)
	{
		return Degrees * Pi / 180.0;
	}

	double Dot(const FVec3& A, const FVec3& B)
	{
		return A.X * B.X + A.Y * B.Y + A.Z * B.Z;
	}

	FVec3 Sub(const FVec3& A, const FVec3& B)
	{
		return FVec3{A.X - B.X, A.Y - B.Y, A.Z - B.Z};
	}

	/** A camera as Unreal defines it: FRotator + location, CineCamera filmback and focal length. */
	struct FTrueCamera
	{
		double Pitch = 0.0;
		double Yaw = 0.0;
		double Roll = 0.0;
		FVec3 Location;
		double FocalMM = 35.0;
		double SensorMM = 36.0; // along the longer image side
		double Width = 1920.0;
		double Height = 1080.0;

		FVec3 X, Y, Z; // forward, right, up

		void Build()
		{
			// FRotationTranslationMatrix, rows = axes.
			const double SP = std::sin(Radians(Pitch)), CP = std::cos(Radians(Pitch));
			const double SY = std::sin(Radians(Yaw)), CY = std::cos(Radians(Yaw));
			const double SR = std::sin(Radians(Roll)), CR = std::cos(Radians(Roll));
			X = FVec3{CP * CY, CP * SY, SP};
			Y = FVec3{SR * SP * CY - CR * SY, SR * SP * SY + CR * CY, -SR * CP};
			Z = FVec3{-(CR * SP * CY + SR * SY), CY * SR - CR * SP * SY, CR * CP};
		}

		double FocalPixels() const
		{
			return FocalMM / SensorMM * (Width > Height ? Width : Height);
		}

		/** Unreal's perspective projection: view space is (right, up, forward); screen Y goes down. */
		FVec2 Project(const FVec3& World) const
		{
			const FVec3 D = Sub(World, Location);
			const double Forward = Dot(X, D);
			const double F = FocalPixels();
			return FVec2{0.5 * Width + F * Dot(Y, D) / Forward, 0.5 * Height - F * Dot(Z, D) / Forward};
		}

		bool InFront(const FVec3& World) const
		{
			return Dot(X, Sub(World, Location)) > 1.0;
		}

		/** Label for "towards the vanishing point in front of the camera" of a world axis. */
		EWorldAxis Toward(int Axis) const
		{
			const double Component = Axis == 0 ? X.X : (Axis == 1 ? X.Y : X.Z);
			return static_cast<EWorldAxis>(Axis * 2 + (Component >= 0.0 ? 0 : 1));
		}
	};

	void SetLine(FInput& Input, EHandle Start, const FTrueCamera& Camera, const FVec3& A, const FVec3& B)
	{
		Input.Handles[HandleIndex(Start)] = Camera.Project(A);
		Input.Handles[HandleIndex(Start) + 1] = Camera.Project(B);
	}

	FVec3 AxisVector(int Axis, double Length)
	{
		return FVec3{Axis == 0 ? Length : 0.0, Axis == 1 ? Length : 0.0, Axis == 2 ? Length : 0.0};
	}

	FVec3 Along(const FVec3& Base, int Axis, double Length)
	{
		const FVec3 A = AxisVector(Axis, Length);
		return FVec3{Base.X + A.X, Base.Y + A.Y, Base.Z + A.Z};
	}

	/** Two vanishing point input from edges along world axes Axis1 and Axis2. */
	FInput MakeTwoPointInput(const FTrueCamera& Camera, int Axis1, int Axis2)
	{
		FInput Input;
		Input.ImageWidth = Camera.Width;
		Input.ImageHeight = Camera.Height;
		Input.Mode = ESolveMode::TwoVanishingPoints;
		Input.SensorMM = Camera.SensorMM;
		Input.Axis1 = Camera.Toward(Axis1);
		Input.Axis2 = Camera.Toward(Axis2);

		// Edges of a box near the origin: two parallel edges per axis.
		const int Other = 3 - Axis1 - Axis2;
		const FVec3 BaseA1 = AxisVector(Axis2, 60.0);
		const FVec3 BaseB1 = Along(AxisVector(Axis2, 60.0), Other, 220.0);
		SetLine(Input, EHandle::VP1LineAStart, Camera, BaseA1, Along(BaseA1, Axis1, 300.0));
		SetLine(Input, EHandle::VP1LineBStart, Camera, BaseB1, Along(BaseB1, Axis1, 300.0));
		const FVec3 BaseA2 = AxisVector(Axis1, 40.0);
		const FVec3 BaseB2 = Along(AxisVector(Axis1, 40.0), Other, 180.0);
		SetLine(Input, EHandle::VP2LineAStart, Camera, BaseA2, Along(BaseA2, Axis2, 300.0));
		SetLine(Input, EHandle::VP2LineBStart, Camera, BaseB2, Along(BaseB2, Axis2, 300.0));

		Input.Handles[HandleIndex(EHandle::Origin)] = Camera.Project(FVec3{});
		Input.Scale = EScaleMode::CameraDistance;
		Input.CameraDistance = std::sqrt(Dot(Camera.Location, Camera.Location));
		return Input;
	}

	void CheckCamera(const FResult& Result, const FTrueCamera& Camera, const std::string& Name, double LocationTolerance = 0.05)
	{
		Check(Result.bValid, Name + ": solved (" + Result.Error + ")");
		if (!Result.bValid)
		{
			return;
		}
		CheckNear(Result.FocalMM, Camera.FocalMM, 1e-6 * Camera.FocalMM, Name + ": focal length mm");
		CheckNear(Result.FocalPixels, Camera.FocalPixels(), 1e-6 * Camera.FocalPixels(), Name + ": focal length px");
		CheckNear(Dot(Result.Forward, Camera.X), 1.0, 1e-9, Name + ": forward axis");
		CheckNear(Dot(Result.Right, Camera.Y), 1.0, 1e-9, Name + ": right axis");
		CheckNear(Dot(Result.Up, Camera.Z), 1.0, 1e-9, Name + ": up axis");
		CheckNear(Result.Location.X, Camera.Location.X, LocationTolerance, Name + ": location X");
		CheckNear(Result.Location.Y, Camera.Location.Y, LocationTolerance, Name + ": location Y");
		CheckNear(Result.Location.Z, Camera.Location.Z, LocationTolerance, Name + ": location Z");
		CheckNear(Result.Pitch, Camera.Pitch, 1e-6, Name + ": pitch");
		CheckNear(Result.Yaw, Camera.Yaw, 1e-6, Name + ": yaw");
		CheckNear(Result.Roll, Camera.Roll, 1e-6, Name + ": roll");

		// The solved camera must reproject world points exactly where the true camera does.
		const FVec3 Points[] = {{0, 0, 0}, {250, -80, 0}, {-120, 330, 90}, {40, 60, 400}, {600, 500, -50}};
		for (const FVec3& P : Points)
		{
			if (!Camera.InFront(P))
			{
				continue;
			}
			FVec2 Pixel;
			Check(ProjectPoint(Result, P, Pixel), Name + ": point in front projects");
			const FVec2 Expected = Camera.Project(P);
			CheckNear(Pixel.X, Expected.X, 1e-3, Name + ": reprojection x");
			CheckNear(Pixel.Y, Expected.Y, 1e-3, Name + ": reprojection y");
		}
	}

	FTrueCamera Camera(double Pitch, double Yaw, double Roll, FVec3 Location, double FocalMM, double Width, double Height)
	{
		FTrueCamera C;
		C.Pitch = Pitch;
		C.Yaw = Yaw;
		C.Roll = Roll;
		C.Location = Location;
		C.FocalMM = FocalMM;
		C.Width = Width;
		C.Height = Height;
		C.Build();
		return C;
	}

	void TestRotatorMatchesUnreal()
	{
		std::printf("Rotator conversion matches FMatrix::Rotator()\n");
		const double Cases[][3] = {{0, 0, 0}, {-10, 45, 0}, {20, -130, 5}, {-60, 170, -30}, {5, 90, 179}, {-89, -45, 10}};
		for (const auto& Case : Cases)
		{
			FTrueCamera C = Camera(Case[0], Case[1], Case[2], FVec3{}, 35, 100, 100);
			double P = 0, Y = 0, R = 0;
			RotatorFromAxes(C.X, C.Y, C.Z, P, Y, R);
			char Name[64];
			std::snprintf(Name, sizeof(Name), "rotator (%g, %g, %g)", Case[0], Case[1], Case[2]);
			CheckNear(P, Case[0], 1e-6, std::string(Name) + " pitch");
			CheckNear(Y, Case[1], 1e-6, std::string(Name) + " yaw");
			CheckNear(R, Case[2], 1e-6, std::string(Name) + " roll");
		}
	}

	void TestTwoVanishingPoints()
	{
		std::printf("Two vanishing points\n");
		{
			const FTrueCamera C = Camera(-8, 40, 2, FVec3{-700, -600, 170}, 35, 1920, 1080);
			CheckCamera(Solve(MakeTwoPointInput(C, 0, 1)), C, "corner X/Y");
		}
		{
			// Swapped: VP1 = Y, VP2 = X.
			const FTrueCamera C = Camera(-8, 40, 2, FVec3{-700, -600, 170}, 35, 1920, 1080);
			CheckCamera(Solve(MakeTwoPointInput(C, 1, 0)), C, "corner Y/X");
		}
		{
			// Looking up at a tall building: vertical edges converge (VP on Z).
			const FTrueCamera C = Camera(25, -150, -3, FVec3{900, 500, 150}, 24, 4000, 6000);
			CheckCamera(Solve(MakeTwoPointInput(C, 2, 0)), C, "portrait Z/X");
			CheckCamera(Solve(MakeTwoPointInput(C, 1, 2)), C, "portrait Y/Z");
		}
		{
			// Telephoto, steep downward view.
			const FTrueCamera C = Camera(-35, 120, 0, FVec3{1500, -2500, 2200}, 120, 6000, 4000);
			CheckCamera(Solve(MakeTwoPointInput(C, 0, 1)), C, "telephoto", 0.5);
		}
	}

	void TestOneVanishingPoint()
	{
		std::printf("One vanishing point\n");
		const FTrueCamera Cameras[] = {
			Camera(-6, 3, 1.5, FVec3{-900, 40, 165}, 28, 1920, 1080),     // down a corridor
			Camera(-12, -70, -4, FVec3{300, 800, 220}, 50, 3000, 2000),   // road towards -Y
			Camera(4, 178, 0, FVec3{1200, -30, 120}, 18, 1080, 1920),      // portrait, looking along -X
		};
		int Index = 0;
		for (const FTrueCamera& C : Cameras)
		{
			const std::string Name = "1VP camera " + std::to_string(++Index);
			// The main direction is the axis the camera looks along most.
			const int Axis1 = std::fabs(C.X.X) > std::fabs(C.X.Y) ? 0 : 1;
			const int Axis2 = 1 - Axis1;

			FInput Input;
			Input.ImageWidth = C.Width;
			Input.ImageHeight = C.Height;
			Input.Mode = ESolveMode::OneVanishingPoint;
			Input.SensorMM = C.SensorMM;
			Input.FocalMM = C.FocalMM;
			Input.Axis1 = C.Toward(Axis1);
			Input.Axis2 = static_cast<EWorldAxis>(Axis2 * 2); // +Axis2: the horizon line points along +Axis2

			const FVec3 A{Axis1 == 0 ? 0.0 : -150.0, Axis1 == 0 ? -150.0 : 0.0, 0.0};
			const FVec3 B{Axis1 == 0 ? 0.0 : 150.0, Axis1 == 0 ? 150.0 : 0.0, 250.0};
			const double Toward = AxisSign(Input.Axis1) * 400.0;
			SetLine(Input, EHandle::VP1LineAStart, C, A, Along(A, Axis1, Toward));
			SetLine(Input, EHandle::VP1LineBStart, C, B, Along(B, Axis1, Toward));

			// The horizon in the photo: the line through the vanishing points of axis 1 and axis 2,
			// drawn in the direction +Axis2 moves things in the image.
			const FVec3 Far1 = Along(C.Location, Axis1, AxisSign(Input.Axis1) * 1e7);
			const FVec3 Far2 = Along(Far1, Axis2, 1e5);
			const FVec2 P1 = C.Project(Far1);
			const FVec2 P2 = C.Project(Far2);
			const double DX = P2.X - P1.X, DY = P2.Y - P1.Y;
			const double L = std::hypot(DX, DY);
			// Anywhere in the photo: only its direction matters.
			const FVec2 Start{0.3 * C.Width, 0.4 * C.Height};
			Input.Handles[HandleIndex(EHandle::HorizonStart)] = Start;
			Input.Handles[HandleIndex(EHandle::HorizonEnd)] = FVec2{Start.X + 500.0 * DX / L, Start.Y + 500.0 * DY / L};

			Input.Handles[HandleIndex(EHandle::Origin)] = C.Project(FVec3{});
			Input.Scale = EScaleMode::CameraDistance;
			Input.CameraDistance = std::sqrt(Dot(C.Location, C.Location));
			CheckCamera(Solve(Input), C, Name);
		}
	}

	void TestScaleModes()
	{
		std::printf("Scale modes\n");
		const FTrueCamera C = Camera(-10, 35, 1, FVec3{-650, -480, 155}, 32, 2400, 1600);
		FInput Input = MakeTwoPointInput(C, 0, 1);

		Input.Scale = EScaleMode::CameraHeight;
		Input.CameraHeight = C.Location.Z;
		Input.CameraDistance = 1.0; // must be ignored
		CheckCamera(Solve(Input), C, "camera height");

		Input.Scale = EScaleMode::ReferenceLength;
		for (int Axis = 0; Axis < 3; ++Axis)
		{
			for (double Length : {180.0, -120.0})
			{
				Input.ReferenceAxis = Axis;
				Input.ReferenceLength = std::fabs(Length);
				const FVec2 End = C.Project(AxisVector(Axis, Length));
				// Put the handle 5 px off the axis line, sideways: it must be moved back onto it.
				const FVec2 Origin = C.Project(FVec3{});
				const double DX = End.X - Origin.X, DY = End.Y - Origin.Y, L = std::hypot(DX, DY);
				Input.Handles[HandleIndex(EHandle::ReferenceEnd)] = FVec2{End.X - 5.0 * DY / L, End.Y + 5.0 * DX / L};
				const std::string Name = "reference axis " + std::to_string(Axis) + " length " + std::to_string(Length);
				const FResult Result = Solve(Input);
				CheckCamera(Result, C, Name);
				if (Result.bValid)
				{
					// Moving it again along the line must not change the result.
					Input.Handles[HandleIndex(EHandle::ReferenceEnd)] = Result.ReferenceEndOnAxis;
					const FResult Again = Solve(Input);
					CheckNear(Again.DistanceToOrigin, Result.DistanceToOrigin, 1e-6, Name + ": stable after moving onto the axis");
					CheckNear(Result.ReferenceEndOnAxis.X, End.X, 1e-6, Name + ": handle moved onto the axis (x)");
					CheckNear(Result.ReferenceEndOnAxis.Y, End.Y, 1e-6, Name + ": handle moved onto the axis (y)");
				}
			}
		}

		// Past the vanishing point: behind the camera.
		Input.ReferenceAxis = 0;
		const FResult Base = Solve(Input);
		if (Base.bValid)
		{
			const FVec2 Origin = Input.Handles[HandleIndex(EHandle::Origin)];
			const FVec2 VP = Base.VanishingPoints[0];
			Input.Handles[HandleIndex(EHandle::ReferenceEnd)] = FVec2{VP.X + (VP.X - Origin.X) * 0.5, VP.Y + (VP.Y - Origin.Y) * 0.5};
			const FResult Past = Solve(Input);
			Check(!Past.bValid && !Past.Error.empty(), "reference handle past the vanishing point is rejected");
		}
	}

	void TestErrors()
	{
		std::printf("Errors\n");
		const FTrueCamera C = Camera(-8, 40, 2, FVec3{-700, -600, 170}, 35, 1920, 1080);
		{
			FInput Input = MakeTwoPointInput(C, 0, 1);
			Input.Axis2 = EWorldAxis::NegX;
			const FResult R = Solve(Input);
			Check(!R.bValid && R.Error.find("different axes") != std::string::npos, "same axis twice is rejected");
		}
		{
			FInput Input = MakeTwoPointInput(C, 0, 1);
			// Make the VP1 lines parallel.
			const FVec2 A0 = Input.Handles[HandleIndex(EHandle::VP1LineAStart)];
			const FVec2 A1 = Input.Handles[HandleIndex(EHandle::VP1LineAEnd)];
			const FVec2 B0 = Input.Handles[HandleIndex(EHandle::VP1LineBStart)];
			Input.Handles[HandleIndex(EHandle::VP1LineBEnd)] = FVec2{B0.X + (A1.X - A0.X), B0.Y + (A1.Y - A0.Y)};
			const FResult R = Solve(Input);
			Check(!R.bValid && R.Error.find("parallel") != std::string::npos, "parallel lines are rejected");
		}
		{
			FInput Input = MakeTwoPointInput(C, 0, 1);
			// Both vanishing points on the same side: no real focal length.
			for (int H = HandleIndex(EHandle::VP2LineAStart); H <= HandleIndex(EHandle::VP2LineBEnd); ++H)
			{
				Input.Handles[H] = Input.Handles[H - 4];
				Input.Handles[H].Y += 7.0;
			}
			const FResult R = Solve(Input);
			Check(!R.bValid && R.Error.find("real camera") != std::string::npos, "impossible vanishing points are rejected");
		}
		{
			FInput Input = MakeTwoPointInput(C, 0, 1);
			Input.Handles[HandleIndex(EHandle::VP1LineAEnd)] = Input.Handles[HandleIndex(EHandle::VP1LineAStart)];
			const FResult R = Solve(Input);
			Check(!R.bValid && R.Error.find("no length") != std::string::npos, "zero-length line is rejected");
		}
		{
			FInput Input = MakeTwoPointInput(C, 0, 1);
			Input.Scale = EScaleMode::CameraHeight;
			Input.CameraHeight = 150.0;
			// Origin above the horizon.
			Input.Handles[HandleIndex(EHandle::Origin)] = FVec2{960.0, -2000.0};
			const FResult R = Solve(Input);
			Check(!R.bValid && R.Error.find("horizon") != std::string::npos, "camera height with the origin above the horizon is rejected");
		}
		{
			FInput Input;
			const FResult R = Solve(Input);
			Check(!R.bValid, "no image is rejected");
		}
		{
			// Flipping one axis sign turns the world upside down: solved, but with a warning.
			FInput Input = MakeTwoPointInput(C, 0, 1);
			Input.Axis1 = Input.Axis1 == EWorldAxis::PosX ? EWorldAxis::NegX : EWorldAxis::PosX;
			const FResult R = Solve(Input);
			bool bWarned = false;
			for (const std::string& W : R.Warnings)
			{
				bWarned = bWarned || W.find("upside down") != std::string::npos;
			}
			Check(R.bValid && R.Up.Z < 0.0 && bWarned, "flipped axis gives an upside-down warning");
		}
	}

	void TestDefaults()
	{
		std::printf("Default handle layouts\n");
		const double Sizes[][2] = {{1920, 1080}, {6000, 4000}, {1024, 768}, {4000, 6000}, {1080, 1920}, {1000, 1000}};
		for (const auto& Size : Sizes)
		{
			for (ESolveMode Mode : {ESolveMode::TwoVanishingPoints, ESolveMode::OneVanishingPoint})
			{
				FInput Input;
				Input.ImageWidth = Size[0];
				Input.ImageHeight = Size[1];
				Input.Mode = Mode;
				ResetHandles(Input);
				char Name[96];
				std::snprintf(Name, sizeof(Name), "defaults %gx%g %s", Size[0], Size[1], Mode == ESolveMode::TwoVanishingPoints ? "2VP" : "1VP");
				for (EScaleMode Scale : {EScaleMode::CameraDistance, EScaleMode::CameraHeight, EScaleMode::ReferenceLength})
				{
					Input.Scale = Scale;
					const FResult R = Solve(Input);
					Check(R.bValid, std::string(Name) + " solves with scale mode " + std::to_string(static_cast<int>(Scale)) + " (" + R.Error + ")");
					Check(R.Up.Z > 0.5, std::string(Name) + " is upright");
					Check(R.Warnings.empty(), std::string(Name) + " has no warnings");
					Check(R.FocalMM > 10.0 && R.FocalMM < 80.0, std::string(Name) + " has a normal focal length");
					FVec2 Origin;
					Check(ProjectPoint(R, FVec3{}, Origin)
						&& std::fabs(Origin.X - Input.Handles[HandleIndex(EHandle::Origin)].X) < 1e-6
						&& std::fabs(Origin.Y - Input.Handles[HandleIndex(EHandle::Origin)].Y) < 1e-6,
						std::string(Name) + " puts the origin on the origin handle");
				}
			}
		}
	}

	void TestProjectSegment()
	{
		std::printf("Segment projection\n");
		const FTrueCamera C = Camera(-8, 40, 2, FVec3{-700, -600, 170}, 35, 1920, 1080);
		const FResult R = Solve(MakeTwoPointInput(C, 0, 1));
		FVec2 A, B;
		Check(ProjectSegment(R, FVec3{0, 0, 0}, FVec3{300, 0, 0}, A, B), "segment in front projects");
		const FVec3 Behind{C.Location.X - 1000.0 * C.X.X, C.Location.Y - 1000.0 * C.X.Y, C.Location.Z - 1000.0 * C.X.Z};
		const FVec3 Behind2{Behind.X + 50.0, Behind.Y, Behind.Z};
		Check(!ProjectSegment(R, Behind, Behind2, A, B), "segment behind the camera is dropped");
		// Crossing the camera plane: clipped, the visible end stays exact.
		Check(ProjectSegment(R, Behind, FVec3{0, 0, 0}, A, B), "segment crossing the near plane is clipped");
		const FVec2 Origin = C.Project(FVec3{});
		CheckNear(B.X, Origin.X, 1e-6, "clipped segment keeps its visible end (x)");
		CheckNear(B.Y, Origin.Y, 1e-6, "clipped segment keeps its visible end (y)");
	}
}

int main()
{
	TestRotatorMatchesUnreal();
	TestTwoVanishingPoints();
	TestOneVanishingPoint();
	TestScaleModes();
	TestErrors();
	TestDefaults();
	TestProjectSegment();

	std::printf("\n%d checks, %d failed\n", Checks, Failures);
	return Failures == 0 ? 0 : 1;
}
