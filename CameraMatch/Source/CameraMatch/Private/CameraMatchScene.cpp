#include "CameraMatchScene.h"

#include "AssetImportTask.h"
#include "AssetToolsModule.h"
#include "CineCameraActor.h"
#include "CineCameraComponent.h"
#include "Editor.h"
#include "Engine/BlendableInterface.h"
#include "Engine/Texture2D.h"
#include "Factories/MaterialFactoryNew.h"
#include "Factories/MaterialInstanceConstantFactoryNew.h"
#include "IAssetTools.h"
#include "LevelEditorSubsystem.h"
#include "MaterialEditingLibrary.h"
#include "Materials/Material.h"
#include "Materials/MaterialExpressionCustom.h"
#include "Materials/MaterialExpressionScalarParameter.h"
#include "Materials/MaterialExpressionSceneTexture.h"
#include "Materials/MaterialExpressionScreenPosition.h"
#include "Materials/MaterialExpressionTextureSampleParameter2D.h"
#include "Materials/MaterialInstanceConstant.h"
#include "Misc/EngineVersionComparison.h"
#include "Misc/PackageName.h"
#include "Misc/Paths.h"
#include "Modules/ModuleManager.h"
#include "ObjectTools.h"
#include "Subsystems/EditorActorSubsystem.h"
#include "UObject/StrongObjectPtr.h"

#define LOCTEXT_NAMESPACE "CameraMatch"

namespace CameraMatchScenePrivate
{
	const TCHAR* const AssetFolder = TEXT("/Game/CameraMatch");
	const TCHAR* const BackplateFolder = TEXT("/Game/CameraMatch/Backplates");
	const TCHAR* const MaterialName = TEXT("M_CameraMatchBackplate");
	const TCHAR* const StateTagPrefix = TEXT("CameraMatch:");

	const TCHAR* const PlateParameter = TEXT("Backplate");
	const TCHAR* const OpacityParameter = TEXT("Opacity");
	const TCHAR* const BehindParameter = TEXT("BehindScene");
	const TCHAR* const SkyDepthParameter = TEXT("SkyDepth");

	// Runs after the tonemapper, where colors are display (sRGB) encoded, so the photo is encoded
	// the same way and shows its original pixel values instead of being tonemapped.
	const TCHAR* const CompositeCode = TEXT(
		"float3 Plate = saturate(PlateRGB.rgb);\n"
		"float3 Encoded = lerp(Plate * 12.92, 1.055 * pow(Plate, 1.0 / 2.4) - 0.055, step(0.0031308, Plate));\n"
		"float Mask = lerp(1.0, step(SkyDepth, SceneDepthCm.r), saturate(PlateBehind));\n"
		"return lerp(SceneRGB.rgb, Encoded, saturate(PlateOpacity) * Mask);\n");

	FString MaterialObjectPath()
	{
		return FString(AssetFolder) / MaterialName + TEXT(".") + MaterialName;
	}

	IAssetTools& AssetTools()
	{
		return FModuleManager::LoadModuleChecked<FAssetToolsModule>("AssetTools").Get();
	}

	FString SafeName(const FString& Name)
	{
		FString Safe = ObjectTools::SanitizeObjectName(Name).Replace(TEXT(" "), TEXT("_"));
		return Safe.IsEmpty() ? FString(TEXT("Photo")) : Safe;
	}

	/** The post-process material that blends the photo over (or behind) what the camera sees. */
	UMaterial* GetOrCreateMaterial(UTexture2D* DefaultTexture, FText& OutError)
	{
		if (UObject* Existing = LoadObject<UObject>(nullptr, *MaterialObjectPath(), nullptr, LOAD_NoWarn | LOAD_Quiet))
		{
			if (UMaterial* ExistingMaterial = Cast<UMaterial>(Existing))
			{
				return ExistingMaterial;
			}
			OutError = FText::Format(LOCTEXT("MaterialBlocked", "{0} exists but isn't a material. Rename or delete it."), FText::FromString(MaterialObjectPath()));
			return nullptr;
		}

		UMaterialFactoryNew* Factory = NewObject<UMaterialFactoryNew>();
		UMaterial* Material = Cast<UMaterial>(AssetTools().CreateAsset(MaterialName, AssetFolder, UMaterial::StaticClass(), Factory));
		if (!Material)
		{
			OutError = LOCTEXT("MaterialFailed", "Couldn't create the backplate material in /Game/CameraMatch.");
			return nullptr;
		}

		Material->MaterialDomain = MD_PostProcess;
#if UE_VERSION_OLDER_THAN(5, 3, 0)
		Material->BlendableLocation = BL_AfterTonemapping;
#else
		Material->BlendableLocation = BL_SceneColorAfterTonemapping;
#endif

		auto Create = [Material](UClass* Class, int32 X, int32 Y)
		{
			return UMaterialEditingLibrary::CreateMaterialExpression(Material, Class, X, Y);
		};
		auto MakeScalar = [&Create](const TCHAR* Name, float Default, int32 Y)
		{
			UMaterialExpressionScalarParameter* Scalar = Cast<UMaterialExpressionScalarParameter>(
				Create(UMaterialExpressionScalarParameter::StaticClass(), -700, Y));
			if (Scalar)
			{
				Scalar->ParameterName = FName(Name);
				Scalar->DefaultValue = Default;
			}
			return Scalar;
		};

		UMaterialExpressionScreenPosition* ScreenPosition = Cast<UMaterialExpressionScreenPosition>(
			Create(UMaterialExpressionScreenPosition::StaticClass(), -1000, 0));
		UMaterialExpressionTextureSampleParameter2D* Plate = Cast<UMaterialExpressionTextureSampleParameter2D>(
			Create(UMaterialExpressionTextureSampleParameter2D::StaticClass(), -700, 0));
		UMaterialExpressionSceneTexture* SceneColor = Cast<UMaterialExpressionSceneTexture>(
			Create(UMaterialExpressionSceneTexture::StaticClass(), -700, -250));
		UMaterialExpressionSceneTexture* SceneDepth = Cast<UMaterialExpressionSceneTexture>(
			Create(UMaterialExpressionSceneTexture::StaticClass(), -700, 250));
		UMaterialExpressionScalarParameter* Opacity = MakeScalar(OpacityParameter, 0.5f, 400);
		UMaterialExpressionScalarParameter* Behind = MakeScalar(BehindParameter, 0.f, 500);
		UMaterialExpressionScalarParameter* SkyDepth = MakeScalar(SkyDepthParameter, 1.0e6f, 600);
		UMaterialExpressionCustom* Composite = Cast<UMaterialExpressionCustom>(
			Create(UMaterialExpressionCustom::StaticClass(), -350, 0));
		if (!ScreenPosition || !Plate || !SceneColor || !SceneDepth || !Opacity || !Behind || !SkyDepth || !Composite)
		{
			OutError = LOCTEXT("MaterialNodesFailed", "Couldn't build the backplate material's nodes.");
			return nullptr;
		}

		// The photo, sampled at the screen position, so it fills the camera's frame exactly.
		Plate->ParameterName = FName(PlateParameter);
		Plate->Texture = DefaultTexture;
		Plate->AutoSetSampleType();
		Plate->Coordinates.Connect(0, ScreenPosition);
		SceneColor->SceneTextureId = PPI_PostProcessInput0;
		SceneDepth->SceneTextureId = PPI_SceneDepth;

		struct FNamedInput
		{
			const TCHAR* Name;
			UMaterialExpression* Expression;
		};
		const FNamedInput Inputs[] = {
			{TEXT("SceneRGB"), SceneColor},
			{TEXT("PlateRGB"), Plate},
			{TEXT("SceneDepthCm"), SceneDepth},
			{TEXT("PlateOpacity"), Opacity},
			{TEXT("PlateBehind"), Behind},
			{TEXT("SkyDepth"), SkyDepth},
		};
		Composite->Description = TEXT("Camera Match backplate");
		Composite->OutputType = CMOT_Float3;
		Composite->Code = CompositeCode;
		Composite->Inputs.Reset();
		for (const FNamedInput& Input : Inputs)
		{
			FCustomInput& CustomInput = Composite->Inputs.AddDefaulted_GetRef();
			CustomInput.InputName = FName(Input.Name);
			CustomInput.Input.Connect(0, Input.Expression);
		}
		UMaterialEditingLibrary::ConnectMaterialProperty(Composite, FString(), MP_EmissiveColor);

		UMaterialEditingLibrary::RecompileMaterial(Material);
		Material->MarkPackageDirty();
		return Material;
	}

	UMaterialInstanceConstant* FindInstance(const ACineCameraActor* Camera)
	{
		const UCineCameraComponent* Component = Camera ? Camera->GetCineCameraComponent() : nullptr;
		if (!Component)
		{
			return nullptr;
		}
		const FString ParentPath = MaterialObjectPath();
		for (const FWeightedBlendable& Blendable : Component->PostProcessSettings.WeightedBlendables.Array)
		{
			UMaterialInstanceConstant* Instance = Cast<UMaterialInstanceConstant>(Blendable.Object);
			if (Instance && Instance->Parent && Instance->Parent->GetPathName() == ParentPath)
			{
				return Instance;
			}
		}
		return nullptr;
	}

	void ApplyOptions(UMaterialInstanceConstant* Instance, const CameraMatchScene::FBackplateOptions& Options)
	{
		UMaterialEditingLibrary::SetMaterialInstanceScalarParameterValue(Instance, FName(OpacityParameter), FMath::Clamp(Options.Opacity, 0.f, 1.f));
		UMaterialEditingLibrary::SetMaterialInstanceScalarParameterValue(Instance, FName(BehindParameter), Options.bBehindScene ? 1.f : 0.f);
		UMaterialEditingLibrary::UpdateMaterialInstance(Instance);
		Instance->MarkPackageDirty();
	}

	/** ';' separates values in the state tag, so escape it (and '%') inside paths. */
	FString Escape(const FString& Value)
	{
		return Value.Replace(TEXT("%"), TEXT("%25")).Replace(TEXT(";"), TEXT("%3B"));
	}

	FString Unescape(const FString& Value)
	{
		return Value.Replace(TEXT("%3B"), TEXT(";")).Replace(TEXT("%25"), TEXT("%"));
	}

	int32 ClampInt(double Value, int32 Min, int32 Max)
	{
		return FMath::Clamp(static_cast<int32>(FMath::RoundToInt(Value)), Min, Max);
	}
}

namespace CameraMatchScene
{
	using namespace CameraMatchScenePrivate;

	UTexture2D* ImportBackplateTexture(const FString& File, FText& OutError)
	{
		FString PackageName;
		FString AssetName;
		AssetTools().CreateUniqueAssetName(FString(BackplateFolder) / (TEXT("T_") + SafeName(FPaths::GetBaseFilename(File))), FString(), PackageName, AssetName);

		TStrongObjectPtr<UAssetImportTask> Task(NewObject<UAssetImportTask>());
		Task->Filename = File;
		Task->DestinationPath = FPackageName::GetLongPackagePath(PackageName);
		Task->DestinationName = AssetName;
		Task->bAutomated = true;
		Task->bReplaceExisting = false;
		Task->bSave = false;
		TArray<UAssetImportTask*> Tasks;
		Tasks.Add(Task.Get());
		AssetTools().ImportAssetTasks(Tasks);

		for (const FString& Path : Task->ImportedObjectPaths)
		{
			if (UTexture2D* Texture = LoadObject<UTexture2D>(nullptr, *Path))
			{
				// The backplate material samples it as a plain 2D texture.
				if (Texture->VirtualTextureStreaming)
				{
					Texture->Modify();
					Texture->VirtualTextureStreaming = false;
					Texture->PostEditChange();
				}
				return Texture;
			}
		}
		OutError = FText::Format(LOCTEXT("ImportFailed", "Couldn't import {0} as a texture. See the Output Log."), FText::FromString(File));
		return nullptr;
	}

	bool CanUseAsBackplate(const UTexture2D* Texture, FText& OutError)
	{
		if (!Texture)
		{
			OutError = LOCTEXT("NoTexture", "No photo texture.");
			return false;
		}
		if (!Texture->SRGB)
		{
			OutError = FText::Format(LOCTEXT("NotSRGB",
				"{0} isn't an sRGB texture (it's linear or HDR), so it can't be used as the backplate. Use a normal photo (JPG/PNG), or tick sRGB in the texture's settings."),
				FText::FromString(Texture->GetName()));
			return false;
		}
		if (Texture->VirtualTextureStreaming)
		{
			OutError = FText::Format(LOCTEXT("VirtualTexture",
				"{0} uses Virtual Texture Streaming, which the backplate material can't sample. Untick it in the texture's settings, or load the photo from its file instead."),
				FText::FromString(Texture->GetName()));
			return false;
		}
		return true;
	}

	ACineCameraActor* CreateCamera(const CameraMatch::FResult& Result, const FString& Label, FText& OutError)
	{
		UEditorActorSubsystem* Actors = GEditor ? GEditor->GetEditorSubsystem<UEditorActorSubsystem>() : nullptr;
		if (!Actors)
		{
			OutError = LOCTEXT("NoEditor", "The editor isn't ready.");
			return nullptr;
		}
		if (GEditor->PlayWorld)
		{
			OutError = LOCTEXT("InPIE", "Stop Play-In-Editor first.");
			return nullptr;
		}

		const FVector Location(Result.Location.X, Result.Location.Y, Result.Location.Z);
		const FRotator Rotation(Result.Pitch, Result.Yaw, Result.Roll);
		ACineCameraActor* Camera = Cast<ACineCameraActor>(Actors->SpawnActorFromClass(ACineCameraActor::StaticClass(), Location, Rotation));
		if (!Camera)
		{
			OutError = LOCTEXT("SpawnFailed", "Couldn't create the camera in the open level.");
			return nullptr;
		}
		Camera->SetActorLabel(Label);
		Camera->SetFolderPath(FName(TEXT("CameraMatch")));
		ApplyCamera(Camera, Result);
		return Camera;
	}

	void ApplyCamera(ACineCameraActor* Camera, const CameraMatch::FResult& Result)
	{
		UCineCameraComponent* Component = Camera ? Camera->GetCineCameraComponent() : nullptr;
		if (!Component || !Result.bValid)
		{
			return;
		}

		Camera->SetActorLocationAndRotation(
			FVector(Result.Location.X, Result.Location.Y, Result.Location.Z),
			FRotator(Result.Pitch, Result.Yaw, Result.Roll), false, nullptr, ETeleportType::TeleportPhysics);

		// Filmback with the photo's aspect ratio, so the frame matches the photo exactly.
		// The Cine Camera recomputes its field of view from these every frame.
		Component->Filmback.SensorWidth = static_cast<float>(Result.SensorWidthMM);
		Component->Filmback.SensorHeight = static_cast<float>(Result.SensorHeightMM);
		Component->Filmback.SensorAspectRatio = Component->Filmback.SensorWidth / FMath::Max(Component->Filmback.SensorHeight, 0.001f);

		// The lens range clamps the focal length, so widen it when needed.
		const float Focal = static_cast<float>(Result.FocalMM);
		Component->LensSettings.MinFocalLength = FMath::Min(Component->LensSettings.MinFocalLength, Focal);
		Component->LensSettings.MaxFocalLength = FMath::Max(Component->LensSettings.MaxFocalLength, Focal);
		Component->CurrentFocalLength = Focal;

		// No depth of field: everything in the photo-matched view stays sharp.
		Component->FocusSettings.FocusMethod = ECameraFocusMethod::Disable;
		Component->SetConstraintAspectRatio(true);
	}

	bool SetBackplate(ACineCameraActor* Camera, UTexture2D* Texture, const FBackplateOptions& Options, FText& OutError)
	{
		UCineCameraComponent* Component = Camera ? Camera->GetCineCameraComponent() : nullptr;
		if (!Component)
		{
			OutError = LOCTEXT("NoCamera", "No camera.");
			return false;
		}
		if (!CanUseAsBackplate(Texture, OutError))
		{
			return false;
		}
		UMaterial* Material = GetOrCreateMaterial(Texture, OutError);
		if (!Material)
		{
			return false;
		}

		UMaterialInstanceConstant* Instance = FindInstance(Camera);
		if (!Instance)
		{
			FString PackageName;
			FString AssetName;
			AssetTools().CreateUniqueAssetName(FString(AssetFolder) / (TEXT("MI_") + SafeName(Camera->GetActorLabel())), FString(), PackageName, AssetName);
			UMaterialInstanceConstantFactoryNew* Factory = NewObject<UMaterialInstanceConstantFactoryNew>();
			Factory->InitialParent = Material;
			Instance = Cast<UMaterialInstanceConstant>(AssetTools().CreateAsset(
				AssetName, FPackageName::GetLongPackagePath(PackageName), UMaterialInstanceConstant::StaticClass(), Factory));
			if (!Instance)
			{
				OutError = LOCTEXT("InstanceFailed", "Couldn't create the backplate material instance in /Game/CameraMatch.");
				return false;
			}

			Component->Modify();
			Component->PostProcessSettings.WeightedBlendables.Array.Add(FWeightedBlendable(1.f, Instance));
			Component->PostProcessBlendWeight = 1.f;
		}

		UMaterialEditingLibrary::SetMaterialInstanceTextureParameterValue(Instance, FName(PlateParameter), Texture);
		ApplyOptions(Instance, Options);
		return true;
	}

	bool SetBackplateOptions(ACineCameraActor* Camera, const FBackplateOptions& Options)
	{
		UMaterialInstanceConstant* Instance = FindInstance(Camera);
		if (!Instance)
		{
			return false;
		}
		ApplyOptions(Instance, Options);
		return true;
	}

	void RemoveBackplate(ACineCameraActor* Camera)
	{
		UMaterialInstanceConstant* Instance = FindInstance(Camera);
		if (!Instance)
		{
			return;
		}
		UCineCameraComponent* Component = Camera->GetCineCameraComponent();
		Component->Modify();
		Component->PostProcessSettings.WeightedBlendables.Array.RemoveAll([Instance](const FWeightedBlendable& Blendable)
		{
			return Blendable.Object == Instance;
		});
	}

	void WriteState(ACineCameraActor* Camera, const CameraMatch::FInput& Input, const FString& TexturePath, const FString& SourceFile,
		const FBackplateOptions& Options)
	{
		if (!Camera)
		{
			return;
		}
		FString State = FString::Printf(
			TEXT("%sv=1;w=%.0f;h=%.0f;mode=%d;a1=%d;a2=%d;sensor=%.4f;focal=%.4f;scale=%d;dist=%.3f;height=%.3f;refaxis=%d;reflen=%.3f;opacity=%.3f;behind=%d;p="),
			StateTagPrefix, Input.ImageWidth, Input.ImageHeight, static_cast<int32>(Input.Mode), static_cast<int32>(Input.Axis1),
			static_cast<int32>(Input.Axis2), Input.SensorMM, Input.FocalMM, static_cast<int32>(Input.Scale), Input.CameraDistance,
			Input.CameraHeight, Input.ReferenceAxis, Input.ReferenceLength, Options.Opacity, Options.bBehindScene ? 1 : 0);
		for (int32 Index = 0; Index < CameraMatch::HandleCount; ++Index)
		{
			State += FString::Printf(TEXT("%s%.2f,%.2f"), Index > 0 ? TEXT("/") : TEXT(""), Input.Handles[Index].X, Input.Handles[Index].Y);
		}
		State += TEXT(";tex=") + Escape(TexturePath);
		// Tags are FNames, which hold up to 1023 characters.
		const FString WithFile = State + TEXT(";file=") + Escape(SourceFile);
		if (WithFile.Len() < 1000)
		{
			State = WithFile;
		}
		if (State.Len() >= 1000)
		{
			return;
		}

		Camera->Tags.RemoveAll([](const FName& Tag)
		{
			return Tag.ToString().StartsWith(StateTagPrefix);
		});
		Camera->Tags.Add(FName(*State));
	}

	bool ReadState(const ACineCameraActor* Camera, CameraMatch::FInput& OutInput, FString& OutTexturePath, FString& OutSourceFile,
		FBackplateOptions& OutOptions)
	{
		if (!Camera)
		{
			return false;
		}
		for (const FName& Tag : Camera->Tags)
		{
			FString State = Tag.ToString();
			if (!State.StartsWith(StateTagPrefix))
			{
				continue;
			}
			State.RightChopInline(FCString::Strlen(StateTagPrefix));

			TArray<FString> Parts;
			State.ParseIntoArray(Parts, TEXT(";"), false);
			TMap<FString, FString> Values;
			for (const FString& Part : Parts)
			{
				FString Key;
				FString Value;
				if (Part.Split(TEXT("="), &Key, &Value))
				{
					Values.Add(Key, Value);
				}
			}
			if (Values.FindRef(TEXT("v")) != TEXT("1"))
			{
				return false;
			}
			auto Number = [&Values](const TCHAR* Key, double Default)
			{
				const FString* Value = Values.Find(Key);
				return Value ? FCString::Atod(**Value) : Default;
			};

			TArray<FString> Points;
			Values.FindRef(TEXT("p")).ParseIntoArray(Points, TEXT("/"), false);
			if (Points.Num() != CameraMatch::HandleCount)
			{
				return false;
			}

			CameraMatch::FInput Input;
			Input.ImageWidth = Number(TEXT("w"), 0.0);
			Input.ImageHeight = Number(TEXT("h"), 0.0);
			Input.Mode = static_cast<CameraMatch::ESolveMode>(ClampInt(Number(TEXT("mode"), 1.0), 0, 1));
			Input.Axis1 = static_cast<CameraMatch::EWorldAxis>(ClampInt(Number(TEXT("a1"), 0.0), 0, 5));
			Input.Axis2 = static_cast<CameraMatch::EWorldAxis>(ClampInt(Number(TEXT("a2"), 2.0), 0, 5));
			Input.SensorMM = Number(TEXT("sensor"), 36.0);
			Input.FocalMM = Number(TEXT("focal"), 35.0);
			Input.Scale = static_cast<CameraMatch::EScaleMode>(ClampInt(Number(TEXT("scale"), 0.0), 0, 2));
			Input.CameraDistance = Number(TEXT("dist"), 1000.0);
			Input.CameraHeight = Number(TEXT("height"), 160.0);
			Input.ReferenceAxis = ClampInt(Number(TEXT("refaxis"), 0.0), 0, 2);
			Input.ReferenceLength = Number(TEXT("reflen"), 100.0);
			for (int32 Index = 0; Index < CameraMatch::HandleCount; ++Index)
			{
				FString X;
				FString Y;
				if (!Points[Index].Split(TEXT(","), &X, &Y))
				{
					return false;
				}
				Input.Handles[Index] = CameraMatch::FVec2{FCString::Atod(*X), FCString::Atod(*Y)};
			}
			if (!(Input.ImageWidth > 0.0 && Input.ImageHeight > 0.0))
			{
				return false;
			}

			OutInput = Input;
			OutTexturePath = Unescape(Values.FindRef(TEXT("tex")));
			OutSourceFile = Unescape(Values.FindRef(TEXT("file")));
			OutOptions.Opacity = static_cast<float>(Number(TEXT("opacity"), 0.5));
			OutOptions.bBehindScene = Number(TEXT("behind"), 0.0) > 0.5;
			return true;
		}
		return false;
	}

	void Pilot(ACineCameraActor* Camera)
	{
		if (!GEditor || !Camera)
		{
			return;
		}
		if (ULevelEditorSubsystem* LevelEditor = GEditor->GetEditorSubsystem<ULevelEditorSubsystem>())
		{
			LevelEditor->PilotLevelActor(Camera);
		}
	}
}

#undef LOCTEXT_NAMESPACE
