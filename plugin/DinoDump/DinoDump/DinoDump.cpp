// DinoDump — ARK: Survival Evolved Server API plugin
// ---------------------------------------------------------------------------
// Dumps tamed dinos and cryopods (any item carrying binary custom data) from
// whatever save the server has loaded.
//
// Commands (type in the in-game admin console, or send over RCON):
//
//   dinodump.check             which game fields/functions this server build
//                              has (also written to the plugin log at startup)
//   dinodump.probe [N]         "dump EVERY property" mode, for working out what
//                              data exists: N tamed dinos (bred ones first) and
//                              N cryopods, each to its own JSON file. Default 3.
//   dinodump.all [wild]        the real dump: every tamed dino + every cryopod
//                              to dinos.jsonl / pods.jsonl / pods.bin.
//                              Add "wild" to include wild dinos too.
//   dinodump.podtest [N]       EXPERIMENTAL: unpack N cryopods with the game's
//                              own cryopod code, dump the dino, delete it again.
//                              Use only on a throwaway copy of a save.
//
// Unattended mode (server launch options, for the batch runner):
//   -DinoDumpAuto              run "dinodump.all" once the server is ready
//   -DinoDumpDelay=60          seconds to wait after "ready" (default 60)
//   -DinoDumpWild              include wild dinos in the auto run
//   -DinoDumpExit              kill the server when done, WITHOUT saving
//
// Output goes under  ShooterGame\Binaries\Win64\ArkApi\Plugins\DinoDump\
//   probe_<map>_<time>\     probe files
//   dumps\<map>_<time>\     full dumps; run.json is written LAST, so its
//                           presence means the dump finished
//
// Nothing here ever saves the world. Run it on copies of your saves anyway.
// ---------------------------------------------------------------------------

#include <API/ARK/Ark.h>
#include <Logger/Logger.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <string>
#include <unordered_map>
#include <vector>

#pragma comment(lib, "ArkApi.lib")

namespace fs = std::filesystem;

namespace DinoDump
{
	constexpr const char* kPluginVersion = "0.5";
	constexpr const char* kRawFormat = "dinodump-raw-v2";
	constexpr size_t kMaxPropertyText = 16384;  // per property value in probe files

	// =======================================================================
	// Crash guards
	// -----------------------------------------------------------------------
	// Reading another program's memory can fault on a bad pointer. These run
	// a piece of work under a Windows structured-exception guard, so one bad
	// dino or item is skipped and counted instead of taking the server down.
	// The guard functions themselves must not own any C++ objects.
	// =======================================================================

	using Thunk = void (*)(void*);

	__declspec(noinline) bool SafeCall(Thunk fn, void* ctx)
	{
		__try
		{
			fn(ctx);
			return true;
		}
		__except (EXCEPTION_EXECUTE_HANDLER)
		{
			return false;
		}
	}

	template <class F>
	bool Guarded(F& f)
	{
		return SafeCall([](void* p) { (*static_cast<F*>(p))(); }, &f);
	}

	// =======================================================================
	// Checking what this server build has
	// -----------------------------------------------------------------------
	// The API finds fields and functions by name in the server's debug
	// symbols. A name that doesn't exist silently resolves to offset 0 (or the
	// module base for functions), which would read garbage or crash. So every
	// field and function is checked once before use.
	// =======================================================================

	std::unordered_map<std::string, bool> g_has_cache;

	bool HasField(const std::string& name)
	{
		auto it = g_has_cache.find(name);
		if (it != g_has_cache.end())
			return it->second;
		const bool ok = GetAddress(static_cast<const void*>(nullptr), name) != 0;
		g_has_cache.emplace(name, ok);
		return ok;
	}

	bool HasFunc(const std::string& name)
	{
		static const LPVOID missing = GetAddress(std::string("DinoDump.__this_function_does_not_exist__"));
		auto it = g_has_cache.find(name);
		if (it != g_has_cache.end())
			return it->second;
		const bool ok = GetAddress(name) != missing;
		g_has_cache.emplace(name, ok);
		return ok;
	}

	const std::vector<std::string> kFieldsUsed = {
		"APrimalDinoCharacter.DinoID1", "APrimalDinoCharacter.DinoID2",
		"APrimalDinoCharacter.TamedName", "APrimalDinoCharacter.TamerString",
		"APrimalDinoCharacter.OwningPlayerName", "APrimalDinoCharacter.OwningPlayerID",
		"APrimalDinoCharacter.ImprinterName", "APrimalDinoCharacter.ImprinterPlayerDataID",
		"APrimalDinoCharacter.TamedOnServerName", "APrimalDinoCharacter.UploadedFromServerName",
		"APrimalDinoCharacter.LatestUploadedFromServerName", "APrimalDinoCharacter.PreviousUploadedFromServerName",
		"APrimalDinoCharacter.DinoDownloadedAtTime", "APrimalDinoCharacter.TamingTeamID",
		"APrimalDinoCharacter.OriginalTargetingTeam", "APrimalDinoCharacter.BabyAge",
		"APrimalDinoCharacter.ColorSetIndices", "APrimalDinoCharacter.RandomMutationsFemale",
		"APrimalDinoCharacter.RandomMutationsMale", "APrimalDinoCharacter.DinoAncestors",
		"APrimalDinoCharacter.DinoAncestorsMale", "APrimalDinoCharacter.DinoNameTag",
		"APrimalCharacter.TribeName", "APrimalCharacter.DescriptiveName",
		"APrimalCharacter.MyCharacterStatusComponent", "APrimalCharacter.MyInventoryComponent",
		"AActor.TargetingTeam", "AActor.OriginalCreationTime", "AActor.RootComponent",
		"USceneComponent.RelativeLocation",
		"UPrimalCharacterStatusComponent.NumberOfLevelUpPointsApplied",
		"UPrimalCharacterStatusComponent.NumberOfLevelUpPointsAppliedTamed",
		"UPrimalCharacterStatusComponent.MaxStatusValues",
		"UPrimalCharacterStatusComponent.BaseCharacterLevel",
		"UPrimalCharacterStatusComponent.ExtraCharacterLevel",
		"UPrimalCharacterStatusComponent.DinoImprintingQuality",
		"UPrimalCharacterStatusComponent.TamedIneffectivenessModifier",
		"UPrimalItem.CustomItemDatas", "UPrimalItem.ItemID", "UPrimalItem.OwnerInventory",
		"UPrimalItem.ItemQuantity", "UPrimalItem.DescriptiveNameBase",
		"UProperty.ArrayDim", "UProperty.ElementSize", "UProperty.PropertyFlags",
		"UProperty.Offset_Internal", "UProperty.PropertyLinkNext", "UStruct.PropertyLink",
	};

	const std::vector<std::string> kFuncsUsed = {
		"UProperty.ExportText_Direct",
		"APrimalDinoCharacter.SpawnFromDinoDataEx",
		"APrimalDinoCharacter.GetDinoData",
		"UGameplayStatics.GetAllActorsOfClass",
		"FWeakObjectPtr.Get",
		"UActorComponent.GetOwner",
		"AActor.Destroy",
		"UStruct.IsChildOf",
	};

	std::vector<std::string> MissingNames()
	{
		std::vector<std::string> out;
		for (const auto& n : kFieldsUsed)
			if (!HasField(n))
				out.push_back(n);
		for (const auto& n : kFuncsUsed)
			if (!HasFunc(n))
				out.push_back(n + "()");
		return out;
	}

	// =======================================================================
	// JSON + string helpers
	// =======================================================================

	std::string Q(const std::string& s)  // JSON string literal
	{
		std::string o;
		o.reserve(s.size() + 2);
		o += '"';
		for (const unsigned char c : s)
		{
			switch (c)
			{
			case '"': o += "\\\""; break;
			case '\\': o += "\\\\"; break;
			case '\n': o += "\\n"; break;
			case '\r': o += "\\r"; break;
			case '\t': o += "\\t"; break;
			default:
				if (c < 0x20)
				{
					char b[8];
					snprintf(b, sizeof b, "\\u%04x", c);
					o += b;
				}
				else
				{
					o += static_cast<char>(c);
				}
			}
		}
		o += '"';
		return o;
	}

	std::string QF(const FString& s) { return Q(s.ToString()); }

	std::string Num(double v)
	{
		if (!std::isfinite(v))
			return "null";
		char b[40];
		snprintf(b, sizeof b, "%.9g", v);
		return b;
	}

	std::string Int(long long v) { return std::to_string(v); }
	std::string UInt(unsigned long long v) { return std::to_string(v); }
	std::string Bool(bool v) { return v ? "true" : "false"; }

	// cut a UTF-8 string to at most n bytes without splitting a character
	void Utf8Truncate(std::string& s, size_t n)
	{
		if (s.size() <= n)
			return;
		while (n > 0 && (static_cast<unsigned char>(s[n]) & 0xC0) == 0x80)
			--n;
		s.resize(n);
	}

	std::string Base64(const unsigned char* data, size_t len)
	{
		static const char* t = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
		std::string o;
		o.reserve((len + 2) / 3 * 4);
		for (size_t i = 0; i < len; i += 3)
		{
			const unsigned v = (data[i] << 16) | ((i + 1 < len ? data[i + 1] : 0) << 8) | (i + 2 < len ? data[i + 2] : 0);
			o += t[(v >> 18) & 63];
			o += t[(v >> 12) & 63];
			o += i + 1 < len ? t[(v >> 6) & 63] : '=';
			o += i + 2 < len ? t[v & 63] : '=';
		}
		return o;
	}

	std::string NowStamp()
	{
		const std::time_t t = std::time(nullptr);
		std::tm tm{};
		localtime_s(&tm, &t);
		char b[32];
		std::strftime(b, sizeof b, "%Y%m%d_%H%M%S", &tm);
		return b;
	}

	std::string NowIso()
	{
		const std::time_t t = std::time(nullptr);
		std::tm tm{};
		gmtime_s(&tm, &t);
		char b[32];
		std::strftime(b, sizeof b, "%Y-%m-%dT%H:%M:%SZ", &tm);
		return b;
	}

	std::string SafeFileName(std::string s)
	{
		for (char& c : s)
			if (c == '<' || c == '>' || c == ':' || c == '"' || c == '/' || c == '\\' || c == '|' || c == '?' ||
				c == '*' || static_cast<unsigned char>(c) < 0x20)
				c = '_';
		return s.empty() ? "unknown" : s;
	}

	std::string NameOf(const FName& n) { return n.ToString().ToString(); }

	std::string ObjName(UObject* o) { return o ? NameOf(o->NameField()) : ""; }

	// "Blueprint'/Game/...'" path for a class, cached (it's slow-ish and we
	// see the same few hundred classes millions of times)
	std::unordered_map<UClass*, std::string> g_bp_cache;

	const std::string& ClassPath(UClass* cls)
	{
		static const std::string empty;
		if (!cls)
			return empty;
		auto it = g_bp_cache.find(cls);
		if (it != g_bp_cache.end())
			return it->second;
		std::string path;
		auto work = [&] { path = ArkApi::IApiUtils::GetClassBlueprint(cls).ToString(); };
		if (!Guarded(work) || path.empty())
			path = ObjName(cls);
		return g_bp_cache.emplace(cls, path).first->second;
	}

	const std::string& ObjClassPath(UObject* o) { return ClassPath(o ? o->ClassField() : nullptr); }

	std::string MapName()
	{
		UWorld* w = ArkApi::GetApiUtils().GetWorld();
		return w ? ObjName(w) : "UnknownMap";
	}

	std::string SessionName()
	{
		std::string s;
		auto work = [&] {
			auto* gs = ArkApi::GetApiUtils().GetGameState();
			if (gs)
				s = gs->ServerSessionNameField().ToString();
		};
		Guarded(work);
		return s;
	}

	fs::path PluginDir() { return fs::path(ArkApi::Tools::GetCurrentDir()) / "ArkApi" / "Plugins" / "DinoDump"; }

	// Set from the launch line (see ReadCommandLine):
	//   -DinoDumpSource="NA-PVE-Official-TheIsland429 (2023-09-30)"  -> dump folder name + source.json
	//   -DinoDumpOut="D:\DinoDump\dumps"                             -> where dump folders go
	std::string g_source_label;   // UTF-8
	std::wstring g_out_root;

	fs::path DumpRoot() { return g_out_root.empty() ? PluginDir() / "dumps" : fs::path(g_out_root); }

	bool WriteFile(const fs::path& p, const std::string& text)
	{
		std::ofstream f(p, std::ios::binary | std::ios::trunc);
		if (!f)
			return false;
		f.write(text.data(), static_cast<std::streamsize>(text.size()));
		return static_cast<bool>(f);
	}

	// =======================================================================
	// Reflection: dump every property the engine knows about on an object
	// =======================================================================

	__declspec(noinline) void ExportInner(UProperty* p, FString* out, void* data, UObject* parent)
	{
		p->ExportText_Direct(out, data, nullptr, parent, 0, nullptr);
	}

	__declspec(noinline) bool ExportSafe(UProperty* p, FString* out, void* data, UObject* parent)
	{
		__try
		{
			ExportInner(p, out, data, parent);
			return true;
		}
		__except (EXCEPTION_EXECUTE_HANDLER)
		{
			return false;
		}
	}

	constexpr unsigned long long CPF_SaveGame = 0x0000000001000000ULL;

	// JSON array of {name, type, saved, value, ...} for every property
	std::string PropertiesJson(UObject* obj)
	{
		std::string o = "[";
		if (!obj || !HasField("UStruct.PropertyLink") || !HasFunc("UProperty.ExportText_Direct"))
			return o + "]";

		UClass* cls = obj->ClassField();
		bool first = true;
		int guard = 0;
		for (UProperty* p = cls ? cls->PropertyLinkField() : nullptr; p && guard < 20000;
		     p = p->PropertyLinkNextField(), ++guard)
		{
			std::string name, type;
			int dim = 1, esz = 0, off = 0;
			unsigned long long flags = 0;
			auto meta = [&] {
				name = NameOf(p->NameField());
				type = p->ClassField() ? NameOf(p->ClassField()->NameField()) : "?";
				dim = (std::max)(1, p->ArrayDimField());
				esz = p->ElementSizeField();
				off = p->Offset_InternalField();
				flags = p->PropertyFlagsField();
			};
			if (!Guarded(meta))
				continue;

			for (int i = 0; i < dim && i < 256; ++i)
			{
				FString val;
				const bool ok = ExportSafe(p, &val, reinterpret_cast<char*>(obj) + off + static_cast<size_t>(i) * esz, obj);
				std::string v;
				if (ok)
				{
					auto conv = [&] { v = val.ToString(); };
					Guarded(conv);
				}
				const bool truncated = v.size() > kMaxPropertyText;
				const size_t full_len = v.size();
				Utf8Truncate(v, kMaxPropertyText);

				if (!first)
					o += ",\n";
				first = false;
				o += "{\"name\":" + Q(name);
				if (dim > 1)
					o += ",\"index\":" + Int(i);
				o += ",\"type\":" + Q(type) + ",\"saved\":" + Bool((flags & CPF_SaveGame) != 0) +
					",\"size\":" + Int(esz) + ",\"offset\":" + Int(off) + ",\"ok\":" + Bool(ok) +
					",\"value\":" + Q(v);
				if (truncated)
					o += ",\"truncated\":true,\"full_length\":" + UInt(full_len);
				o += "}";
			}
		}
		return o + "]";
	}

	// =======================================================================
	// Dino record (the structured, useful-fields version)
	// =======================================================================

	std::string AncestorsJson(TArray<FDinoAncestorsEntry>& arr)
	{
		std::string o = "[";
		bool first = true;
		for (int i = 0; i < arr.Num(); ++i)
		{
			FDinoAncestorsEntry& e = arr[i];
			if (!first)
				o += ",";
			first = false;
			o += "{\"male\":" + QF(e.MaleName) + ",\"male_id1\":" + UInt(e.MaleDinoID1) + ",\"male_id2\":" +
				UInt(e.MaleDinoID2) + ",\"female\":" + QF(e.FemaleName) + ",\"female_id1\":" +
				UInt(e.FemaleDinoID1) + ",\"female_id2\":" + UInt(e.FemaleDinoID2) + "}";
		}
		return o + "]";
	}

	template <typename T>
	std::string ArrayJson(const T* p, int n, bool as_unsigned_byte = false)
	{
		std::string o = "[";
		for (int i = 0; i < n; ++i)
		{
			if (i)
				o += ",";
			if (as_unsigned_byte)
				o += Int(static_cast<unsigned char>(p[i]));
			else
				o += Num(static_cast<double>(p[i]));
		}
		return o + "]";
	}

	bool ActorLocation(AActor* a, FVector& out)
	{
		if (!a || !HasField("AActor.RootComponent") || !HasField("USceneComponent.RelativeLocation"))
			return false;
		USceneComponent* rc = a->RootComponentField();
		if (!rc)
			return false;
		out = rc->RelativeLocationField();
		return true;
	}

	std::string TrimWs(std::string s)
	{
		const char* ws = " \t\r\n";
		const auto b = s.find_first_not_of(ws);
		if (b == std::string::npos)
			return "";
		const auto e = s.find_last_not_of(ws);
		return s.substr(b, e - b + 1);
	}

	// "Blueprint'/Game/X/Y.Y'"  ->  "/Game/X/Y.Y_C"  (same form as the in-game export)
	std::string ExportClassPath(UObject* o)
	{
		std::string p = ObjClassPath(o);
		const std::string pre = "Blueprint'";
		if (p.rfind(pre, 0) == 0 && p.size() > pre.size() + 1 && p.back() == '\'')
			return p.substr(pre.size(), p.size() - pre.size() - 1) + "_C";
		return p;
	}

	// One dino record: the fields of the in-game dino export, plus what the
	// site needs (stat points, server origin, location). Empty strings are
	// left out to keep the files small. Each field is read on its own so a
	// missing one drops just that key, not the record.
	std::string DinoJson(APrimalDinoCharacter* d, const std::string& extra_json = "")
	{
		std::string o = "{";
		auto add = [&](const std::string& key, const std::string& json_value) {
			if (o.size() > 1)
				o += ",";
			o += Q(key) + ":" + json_value;
		};
		auto add_str = [&](const std::string& key, const FString& v) {
			const std::string t = TrimWs(v.ToString());
			if (!t.empty())
				add(key, Q(t));
		};
		auto f = [&](const char* field) { return HasField(field); };

		// --- identity (matches the export's [Dino Data])
		if (f("APrimalDinoCharacter.DinoID1")) add("id1", UInt(d->DinoID1Field()));
		if (f("APrimalDinoCharacter.DinoID2")) add("id2", UInt(d->DinoID2Field()));
		if (f("APrimalDinoCharacter.DinoID1") && f("APrimalDinoCharacter.DinoID2"))
			add("id64", Q(UInt((static_cast<unsigned long long>(d->DinoID1Field()) << 32) | d->DinoID2Field())));
		add("class", Q(ExportClassPath(d)));
		if (f("APrimalDinoCharacter.DinoNameTag")) add("name_tag", Q(NameOf(d->DinoNameTagField())));
		if (f("APrimalCharacter.DescriptiveName")) add_str("species", d->DescriptiveNameField());
		if (f("APrimalDinoCharacter.TamedName")) add_str("name", d->TamedNameField());

		auto bits = [&] {
			add("female", Bool(d->bIsFemale()()));
			if (d->bNeutered()()) add("neutered", "true");
		};
		Guarded(bits);

		if (f("APrimalDinoCharacter.TamerString")) add_str("tamer", d->TamerStringField());
		if (f("APrimalDinoCharacter.OwningPlayerName")) add_str("owner_name", d->OwningPlayerNameField());
		if (f("APrimalDinoCharacter.OwningPlayerID") && d->OwningPlayerIDField() != 0)
			add("owner_player_id", Int(d->OwningPlayerIDField()));
		if (f("APrimalDinoCharacter.ImprinterName")) add_str("imprinter", d->ImprinterNameField());
		if (f("APrimalDinoCharacter.ImprinterPlayerDataID") && d->ImprinterPlayerDataIDField() != 0)
			add("imprinter_player_id", Q(UInt(d->ImprinterPlayerDataIDField())));
		if (f("APrimalCharacter.TribeName")) add_str("tribe", d->TribeNameField());
		if (f("AActor.TargetingTeam")) add("tribe_id", Int(d->TargetingTeamField()));

		// raw counters, exactly as stored (can be huge or negative on old lines)
		if (f("APrimalDinoCharacter.RandomMutationsMale")) add("mutations_paternal", Int(d->RandomMutationsMaleField()));
		if (f("APrimalDinoCharacter.RandomMutationsFemale")) add("mutations_maternal", Int(d->RandomMutationsFemaleField()));
		if (f("APrimalDinoCharacter.BabyAge")) add("baby_age", Num(d->BabyAgeField()));

		// --- levels and stats
		UPrimalCharacterStatusComponent* sc =
			f("APrimalCharacter.MyCharacterStatusComponent") ? d->MyCharacterStatusComponentField() : nullptr;
		if (sc)
		{
			const bool hb = f("UPrimalCharacterStatusComponent.BaseCharacterLevel");
			const bool he = f("UPrimalCharacterStatusComponent.ExtraCharacterLevel");
			if (hb && he) add("level", Int(sc->BaseCharacterLevelField() + sc->ExtraCharacterLevelField()));
			if (hb) add("level_wild", Int(sc->BaseCharacterLevelField()));
			if (f("UPrimalCharacterStatusComponent.DinoImprintingQuality")) add("imprint", Num(sc->DinoImprintingQualityField()));
			if (f("UPrimalCharacterStatusComponent.TamedIneffectivenessModifier"))
				add("taming_effectiveness", Num(1.0 / (1.0 + sc->TamedIneffectivenessModifierField())));
			if (f("UPrimalCharacterStatusComponent.NumberOfLevelUpPointsApplied"))
				add("wild_levels", ArrayJson(sc->NumberOfLevelUpPointsAppliedField()(), 12, true));
			if (f("UPrimalCharacterStatusComponent.NumberOfLevelUpPointsAppliedTamed"))
				add("tamed_levels", ArrayJson(sc->NumberOfLevelUpPointsAppliedTamedField()(), 12, true));
			if (f("UPrimalCharacterStatusComponent.MaxStatusValues"))
				add("max_stats", ArrayJson(sc->MaxStatusValuesField()(), 12));
		}

		// color IDs (the export writes RGB values; IDs map to those and are what breeders use)
		if (f("APrimalDinoCharacter.ColorSetIndices")) add("colors", ArrayJson(d->ColorSetIndicesField()(), 6, true));

		// --- where it came from
		if (f("APrimalDinoCharacter.TamedOnServerName")) add_str("tamed_on_server", d->TamedOnServerNameField());
		if (f("APrimalDinoCharacter.UploadedFromServerName")) add_str("uploaded_from_server", d->UploadedFromServerNameField());
		if (f("APrimalDinoCharacter.LatestUploadedFromServerName")) add_str("latest_uploaded_from_server", d->LatestUploadedFromServerNameField());
		if (f("APrimalDinoCharacter.PreviousUploadedFromServerName")) add_str("previous_uploaded_from_server", d->PreviousUploadedFromServerNameField());
		if (f("AActor.OriginalCreationTime")) add("creation_time", Num(static_cast<double>(d->OriginalCreationTimeField())));

		FVector loc;
		if (ActorLocation(d, loc))
			add("location", "[" + Num(std::round(loc.X)) + "," + Num(std::round(loc.Y)) + "," + Num(std::round(loc.Z)) + "]");

		// --- ancestry: oldest first; the LAST entry of each line is this dino's parents
		if (f("APrimalDinoCharacter.DinoAncestors")) add("ancestors_maternal", AncestorsJson(d->DinoAncestorsField()));
		if (f("APrimalDinoCharacter.DinoAncestorsMale")) add("ancestors_paternal", AncestorsJson(d->DinoAncestorsMaleField()));

		if (!extra_json.empty())
		{
			if (o.size() > 1)
				o += ",";
			o += extra_json;
		}
		return o + "}";
	}

	// =======================================================================
	// Finding things in the world
	// =======================================================================

	struct DinoLists
	{
		std::vector<APrimalDinoCharacter*> tamed, wild;
	};

	DinoLists FindDinos()
	{
		DinoLists out;
		TArray<AActor*> actors;
		UGameplayStatics::GetAllActorsOfClass(reinterpret_cast<UObject*>(ArkApi::GetApiUtils().GetWorld()),
		                                      APrimalDinoCharacter::GetPrivateStaticClass(), &actors);
		for (AActor* a : actors)
		{
			auto* d = static_cast<APrimalDinoCharacter*>(a);
			if (!d)
				continue;
			(d->TargetingTeamField() >= 50000 ? out.tamed : out.wild).push_back(d);
		}
		return out;
	}

	bool HasByteData(UPrimalItem* item)
	{
		TArray<FCustomItemData>& datas = item->CustomItemDatasField();
		for (int i = 0; i < datas.Num(); ++i)
			if (datas[i].CustomDataBytes.ByteArrays.Num() > 0)
				return true;
		return false;
	}

	// Walks every object in memory and calls fn(item) for each real item
	// (not a template) that carries binary custom data — i.e. cryopods,
	// soul traps, and anything else that stores a whole creature.
	template <class Fn>
	void ForEachPod(Fn fn, unsigned long long& objects_scanned, unsigned long long& items_scanned)
	{
		UClass* item_class = UPrimalItem::StaticClass();
		std::unordered_map<UClass*, bool> is_item;
		auto& arr = Globals::GUObjectArray()().ObjObjects;
		const int n = arr.NumElements;
		const int skip_flags = static_cast<int>(EObjectFlags::RF_ClassDefaultObject) |
			static_cast<int>(EObjectFlags::RF_ArchetypeObject) | static_cast<int>(EObjectFlags::RF_PendingKill);

		for (int i = 0; i < n; ++i)
		{
			UObject* obj = arr.GetObjectPtr(i)->Object;
			if (!obj)
				continue;
			++objects_scanned;
			if (static_cast<int>(obj->ObjectFlagsField()) & skip_flags)
				continue;
			UClass* cls = obj->ClassField();
			if (!cls)
				continue;
			auto it = is_item.find(cls);
			if (it == is_item.end())
				it = is_item.emplace(cls, cls->IsChildOf(item_class)).first;
			if (!it->second)
				continue;
			++items_scanned;
			auto* item = static_cast<UPrimalItem*>(obj);
			bool pod = false;
			auto check = [&] { pod = HasByteData(item); };
			if (Guarded(check) && pod)
				if (!fn(item))
					return;
		}
	}

	struct PodOwner
	{
		AActor* actor = nullptr;
		std::string json = "null";
	};

	PodOwner OwnerOf(UPrimalItem* item)
	{
		PodOwner po;
		auto work = [&] {
			UPrimalInventoryComponent* inv = item->OwnerInventoryField().Get(true);
			if (!inv)
				return;
			AActor* a = inv->GetOwner();
			if (!a)
				return;
			po.actor = a;
			std::string o = "{\"blueprint\":" + Q(ObjClassPath(a)) + ",\"object\":" + Q(ObjName(a)) +
				",\"team\":" + Int(a->TargetingTeamField());
			if (a->IsA(APrimalDinoCharacter::GetPrivateStaticClass()))
			{
				auto* d = static_cast<APrimalDinoCharacter*>(a);
				o += ",\"dino_name\":" + QF(d->TamedNameField()) + ",\"dino_id1\":" + UInt(d->DinoID1Field()) +
					",\"dino_id2\":" + UInt(d->DinoID2Field());
			}
			FVector loc;
			if (ActorLocation(a, loc))
				o += ",\"location\":[" + Num(loc.X) + "," + Num(loc.Y) + "," + Num(loc.Z) + "]";
			po.json = o + "}";
		};
		if (!Guarded(work))
			po.json = "null";
		return po;
	}

	// Pod record. Byte arrays go to `bin` (if given) as offset/length,
	// otherwise inline as base64 (used by the probe).
	std::string PodJson(UPrimalItem* item, std::ofstream* bin, unsigned long long* bin_pos)
	{
		std::string o = "{\"blueprint\":" + Q(ObjClassPath(item));
		if (HasField("UPrimalItem.ItemID"))
		{
			const FItemNetID& id = item->ItemIDField();
			o += ",\"item_id1\":" + UInt(id.ItemID1) + ",\"item_id2\":" + UInt(id.ItemID2);
		}
		if (HasField("UPrimalItem.DescriptiveNameBase")) o += ",\"item_name\":" + QF(item->DescriptiveNameBaseField());
		if (HasField("UPrimalItem.ItemQuantity")) o += ",\"quantity\":" + Int(item->ItemQuantityField());
		o += ",\"owner\":" + OwnerOf(item).json;

		o += ",\"custom_data\":[";
		TArray<FCustomItemData>& datas = item->CustomItemDatasField();
		for (int i = 0; i < datas.Num(); ++i)
		{
			FCustomItemData& cd = datas[i];
			if (i)
				o += ",";
			o += "{\"name\":" + Q(NameOf(cd.CustomDataName));

			o += ",\"strings\":[";
			for (int j = 0; j < cd.CustomDataStrings.Num(); ++j)
				o += (j ? "," : "") + QF(cd.CustomDataStrings[j]);
			o += "],\"floats\":[";
			for (int j = 0; j < cd.CustomDataFloats.Num(); ++j)
				o += (j ? "," : "") + Num(cd.CustomDataFloats[j]);
			o += "],\"doubles\":[";
			for (int j = 0; j < cd.CustomDataDoubles.Doubles.Num(); ++j)
				o += (j ? "," : "") + Num(cd.CustomDataDoubles.Doubles[j]);
			o += "],\"names\":[";
			for (int j = 0; j < cd.CustomDataNames.Num(); ++j)
				o += (j ? "," : "") + Q(NameOf(cd.CustomDataNames[j]));
			o += "],\"classes\":[";
			for (int j = 0; j < cd.CustomDataClasses.Num(); ++j)
				o += (j ? "," : "") + Q(ClassPath(cd.CustomDataClasses[j]));
			o += "],\"objects\":[";
			for (int j = 0; j < cd.CustomDataObjects.Num(); ++j)
			{
				UObject* ob = cd.CustomDataObjects[j];
				o += std::string(j ? "," : "") + (ob ? "{\"class\":" + Q(ObjClassPath(ob)) + ",\"name\":" + Q(ObjName(ob)) + "}" : "null");
			}
			o += "],\"byte_arrays\":[";
			for (int j = 0; j < cd.CustomDataBytes.ByteArrays.Num(); ++j)
			{
				TArray<unsigned char>& b = cd.CustomDataBytes.ByteArrays[j].Bytes;
				const size_t len = static_cast<size_t>(b.Num());
				if (j)
					o += ",";
				if (bin && bin_pos)
				{
					o += "{\"offset\":" + UInt(*bin_pos) + ",\"length\":" + UInt(len) + "}";
					if (len)
						bin->write(reinterpret_cast<const char*>(b.GetData()), static_cast<std::streamsize>(len));
					*bin_pos += len;
				}
				else
				{
					o += "{\"length\":" + UInt(len) + ",\"base64\":" + Q(len ? Base64(b.GetData(), len) : "") + "}";
				}
			}
			o += "]}";
		}
		return o + "]}";
	}

	// =======================================================================
	// Commands
	// =======================================================================

	using Reply = std::function<void(const std::string&)>;

	void Log(const std::string& s) { Log::GetLog()->info("{}", s); }

	void CmdCheck(const Reply& reply)
	{
		const auto missing = MissingNames();
		if (missing.empty())
		{
			reply("DinoDump: all " + std::to_string(kFieldsUsed.size() + kFuncsUsed.size()) +
				" fields/functions found on this server build.");
			return;
		}
		std::string m = "DinoDump: missing on this build (" + std::to_string(missing.size()) + "): ";
		for (size_t i = 0; i < missing.size(); ++i)
			m += (i ? ", " : "") + missing[i];
		reply(m);
	}

	void CmdProbe(int count, const Reply& reply)
	{
		const fs::path dir = PluginDir() / ("probe_" + SafeFileName(MapName()) + "_" + NowStamp());
		fs::create_directories(dir);

		// --- dinos: bred ones first, they have ancestry to look at
		DinoLists dl = FindDinos();
		std::stable_sort(dl.tamed.begin(), dl.tamed.end(), [](APrimalDinoCharacter* a, APrimalDinoCharacter* b) {
			bool ab = false, bb = false;
			auto w = [&] { ab = a->DinoAncestorsField().Num() > 0; bb = b->DinoAncestorsField().Num() > 0; };
			Guarded(w);
			return ab && !bb;
		});

		int dinos_done = 0, dinos_failed = 0;
		for (APrimalDinoCharacter* d : dl.tamed)
		{
			if (dinos_done >= count)
				break;
			std::string text;
			auto work = [&] {
				UPrimalCharacterStatusComponent* sc = d->MyCharacterStatusComponentField();
				text = "{\"format\":\"dinodump-probe-v1\",\"map\":" + Q(MapName()) + ",\"session\":" + Q(SessionName()) +
					",\n\"summary\":" + DinoJson(d) + ",\n\"dino_properties\":" + PropertiesJson(d) +
					",\n\"status_component_class\":" + Q(ObjClassPath(sc)) +
					",\n\"status_component_properties\":" + PropertiesJson(sc) + "}\n";
			};
			if (!Guarded(work))
			{
				++dinos_failed;
				continue;
			}
			WriteFile(dir / ("dino_" + std::to_string(dinos_done + 1) + "_" + std::to_string(d->DinoID1Field()) + "_" +
				std::to_string(d->DinoID2Field()) + ".json"), text);
			++dinos_done;
		}

		// --- one wild dino for comparison
		if (!dl.wild.empty())
		{
			std::string text;
			auto work = [&] {
				text = "{\"format\":\"dinodump-probe-v1\",\"summary\":" + DinoJson(dl.wild.front()) +
					",\n\"dino_properties\":" + PropertiesJson(dl.wild.front()) + "}\n";
			};
			if (Guarded(work))
				WriteFile(dir / "wild_dino_1.json", text);
		}

		// --- pods
		int pods_done = 0, pods_failed = 0;
		unsigned long long objs = 0, items = 0;
		ForEachPod([&](UPrimalItem* item) {
			std::string text;
			auto work = [&] {
				text = "{\"format\":\"dinodump-probe-v1\",\"map\":" + Q(MapName()) + ",\n\"summary\":" +
					PodJson(item, nullptr, nullptr) + ",\n\"item_properties\":" + PropertiesJson(item) + "}\n";
			};
			if (Guarded(work))
			{
				WriteFile(dir / ("pod_" + std::to_string(pods_done + 1) + ".json"), text);
				++pods_done;
			}
			else
			{
				++pods_failed;
			}
			return pods_done < count;
		}, objs, items);

		std::string m = "DinoDump probe: " + std::to_string(dinos_done) + " dinos, " + std::to_string(pods_done) +
			" pods written (" + std::to_string(dinos_failed + pods_failed) + " failed). Tamed on map: " +
			std::to_string(dl.tamed.size()) + ". Folder: " + dir.string();
		Log(m);
		reply(m);
	}

	bool g_running = false;

	void CmdAll(bool include_wild, const Reply& reply)
	{
		if (g_running)
		{
			reply("DinoDump: a dump is already running.");
			return;
		}
		g_running = true;
		const auto t0 = std::chrono::steady_clock::now();
		const std::string started = NowIso();
		const std::string map = MapName();
		const std::string session = SessionName();
		fs::path dir = DumpRoot() / fs::u8path(g_source_label.empty() ? SafeFileName(map) + "_" + NowStamp()
		                                                              : SafeFileName(g_source_label));
		if (!g_source_label.empty() && fs::exists(dir))
			dir = DumpRoot() / fs::u8path(SafeFileName(g_source_label) + "_rerun_" + NowStamp());
		fs::create_directories(dir);
		if (!g_source_label.empty())
			WriteFile(dir / "source.json", "{\"label\":" + Q(g_source_label) + "}\n");
		Log("DinoDump: full dump starting -> " + dir.string());

		// --- dinos
		unsigned long long dinos_ok = 0, dinos_failed = 0, wild_ok = 0;
		{
			std::ofstream out(dir / "dinos.jsonl", std::ios::binary | std::ios::trunc);
			DinoLists dl = FindDinos();
			auto dump_list = [&](std::vector<APrimalDinoCharacter*>& list, bool wild, unsigned long long& ok) {
				for (APrimalDinoCharacter* d : list)
				{
					std::string line;
					auto work = [&] { line = DinoJson(d, wild ? "\"wild\":true" : ""); };
					if (Guarded(work))
					{
						line += "\n";
						out.write(line.data(), static_cast<std::streamsize>(line.size()));
						++ok;
					}
					else
					{
						++dinos_failed;
					}
				}
			};
			dump_list(dl.tamed, false, dinos_ok);
			if (include_wild)
				dump_list(dl.wild, true, wild_ok);
			Log("DinoDump: dinos done: " + std::to_string(dinos_ok) + " tamed, " + std::to_string(wild_ok) + " wild, " +
				std::to_string(dinos_failed) + " failed");
		}

		// --- pods
		unsigned long long pods_ok = 0, pods_failed = 0, objs = 0, items = 0, bin_pos = 0;
		{
			std::ofstream out(dir / "pods.jsonl", std::ios::binary | std::ios::trunc);
			std::ofstream bin(dir / "pods.bin", std::ios::binary | std::ios::trunc);
			ForEachPod([&](UPrimalItem* item) {
				std::string line;
				auto work = [&] { line = PodJson(item, &bin, &bin_pos); };
				if (Guarded(work))
				{
					line += "\n";
					out.write(line.data(), static_cast<std::streamsize>(line.size()));
					++pods_ok;
				}
				else
				{
					// rewind past any half-written bytes so later offsets stay right
					bin.seekp(static_cast<std::streamoff>(bin_pos));
					++pods_failed;
				}
				if ((pods_ok + pods_failed) % 100000 == 0)
					Log("DinoDump: pods so far: " + std::to_string(pods_ok));
				return true;
			}, objs, items);
			Log("DinoDump: pods done: " + std::to_string(pods_ok) + " ok, " + std::to_string(pods_failed) + " failed, " +
				std::to_string(items) + " items scanned");
		}

		// --- run.json last: its presence means "finished"
		const double secs = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
		std::string missing = "[";
		const auto miss = MissingNames();
		for (size_t i = 0; i < miss.size(); ++i)
			missing += (i ? "," : "") + Q(miss[i]);
		missing += "]";
		const std::string run = "{\n\"format\":" + Q(kRawFormat) + ",\n\"plugin_version\":" + Q(kPluginVersion) +
			",\n\"map\":" + Q(map) + ",\n\"session\":" + Q(session) + ",\n\"source\":" + Q(g_source_label) + ",\n\"started\":" + Q(started) +
			",\n\"finished\":" + Q(NowIso()) + ",\n\"seconds\":" + Num(secs) +
			",\n\"counts\":{\"tamed_dinos\":" + UInt(dinos_ok) + ",\"wild_dinos\":" + UInt(wild_ok) +
			",\"dinos_failed\":" + UInt(dinos_failed) + ",\"pods\":" + UInt(pods_ok) + ",\"pods_failed\":" +
			UInt(pods_failed) + ",\"items_scanned\":" + UInt(items) + ",\"objects_scanned\":" + UInt(objs) +
			",\"pod_bytes\":" + UInt(bin_pos) + "},\n\"missing_fields\":" + missing + "\n}\n";
		WriteFile(dir / "run.json", run);

		g_running = false;
		const std::string m = "DinoDump: done in " + std::to_string(static_cast<long long>(secs)) + "s: " +
			std::to_string(dinos_ok) + " tamed dinos, " + std::to_string(pods_ok) + " pods. Folder: " + dir.string();
		Log(m);
		reply(m);
	}

	std::string Hex(const unsigned char* p, size_t n)
	{
		static const char* h = "0123456789abcdef";
		std::string o;
		o.reserve(n * 2);
		for (size_t i = 0; i < n; ++i)
		{
			o += h[p[i] >> 4];
			o += h[p[i] & 15];
		}
		return o;
	}

	// Reference: what the game's own "dino -> bytes" function produces for a
	// live dino, so it can be compared byte-for-byte with what's in a pod.
	std::string ReferenceDinoData()
	{
		if (!HasFunc("APrimalDinoCharacter.GetDinoData"))
			return "null";
		DinoLists dl = FindDinos();
		if (dl.tamed.empty())
			return "null";
		APrimalDinoCharacter* d = dl.tamed.front();
		std::string o = "null";
		auto work = [&] {
			FARKDinoData data;
			d->GetDinoData(&data);
			const size_t n = static_cast<size_t>(data.DinoData.Num());
			o = "{\"dino\":" + Q(TrimWs(d->TamedNameField().ToString())) + ",\"class\":" + Q(ClassPath(data.DinoClass)) +
				",\"name_in_map\":" + QF(data.DinoNameInMap) + ",\"dino_name\":" + QF(data.DinoName) +
				",\"length\":" + UInt(n) + ",\"head_hex\":" + Q(n ? Hex(data.DinoData.GetData(), (std::min)(n, size_t(256))) : "") +
				",\"base64\":" + Q(n ? Base64(data.DinoData.GetData(), n) : "") + "}";
		};
		if (!Guarded(work))
			o = "{\"error\":\"GetDinoData crashed\"}";
		return o;
	}

	// Tries to unpack cryopods with the game's own code, several ways, and
	// records exactly what happened for each try.
	void CmdPodTest(int count, const Reply& reply)
	{
		if (!HasFunc("APrimalDinoCharacter.SpawnFromDinoDataEx"))
		{
			reply("DinoDump: SpawnFromDinoDataEx not found on this build; podtest unavailable.");
			return;
		}
		const fs::path dir = PluginDir() / ("podtest_" + SafeFileName(MapName()) + "_" + NowStamp());
		fs::create_directories(dir);
		WriteFile(dir / "reference_live_dino.json", ReferenceDinoData() + "\n");

		UClass* dino_class = APrimalDinoCharacter::GetPrivateStaticClass();
		UWorld* world = ArkApi::GetApiUtils().GetWorld();

		int tried = 0, unpacked = 0;
		unsigned long long objs = 0, items = 0;
		std::string summary;
		ForEachPod([&](UPrimalItem* item) {
			// the "Dino" custom data entry: class + byte blocks + label strings
			UClass* cls = nullptr;
			FCustomItemData* cd = nullptr;
			TArray<FCustomItemData>& datas = item->CustomItemDatasField();
			for (int i = 0; i < datas.Num() && !cd; ++i)
				for (int j = 0; j < datas[i].CustomDataClasses.Num(); ++j)
				{
					UClass* c = datas[i].CustomDataClasses[j];
					if (c && c->IsChildOf(dino_class) && datas[i].CustomDataBytes.ByteArrays.Num() > 0)
					{
						cls = c;
						cd = &datas[i];
						break;
					}
				}
			if (!cd)
				return true;  // not a creature pod (e.g. hover skiff), skip

			++tried;
			FString name_in_map = cd->CustomDataStrings.Num() > 0 ? cd->CustomDataStrings[0] : FString("");
			FString shown_name = cd->CustomDataStrings.Num() > 1 ? cd->CustomDataStrings[1] : FString("");

			PodOwner owner = OwnerOf(item);
			FVector base{0, 0, 0};
			if (owner.actor)
				ActorLocation(owner.actor, base);
			const int team = owner.actor ? owner.actor->TargetingTeamField() : 0;

			std::string blocks = "[";
			for (int j = 0; j < cd->CustomDataBytes.ByteArrays.Num(); ++j)
			{
				TArray<unsigned char>& b = cd->CustomDataBytes.ByteArrays[j].Bytes;
				const size_t n = static_cast<size_t>(b.Num());
				blocks += std::string(j ? "," : "") + "{\"length\":" + UInt(n) + ",\"head_hex\":" +
					Q(n ? Hex(b.GetData(), (std::min)(n, size_t(256))) : "") + ",\"base64\":" + Q(n ? Base64(b.GetData(), n) : "") + "}";
			}
			blocks += "]";

			struct Try
			{
				const char* label;
				int block;        // which byte block to use, -1 = blocks 0+1 joined
				bool new_id;
				float z_offset;
			};
			const Try tries[] = {
				{"block0_high", 0, false, 50000.f},
				{"block0_near", 0, false, 300.f},
				{"block0_newid_near", 0, true, 300.f},
				{"block1_near", 1, false, 300.f},
				{"blocks01_near", -1, false, 300.f},
			};

			std::string attempts = "[";
			std::string result_json = "null";
			bool success = false;
			for (const Try& t : tries)
			{
				if (success)
					break;
				if (t.block >= cd->CustomDataBytes.ByteArrays.Num())
					continue;

				std::string outcome;
				bool duped = false;
				APrimalDinoCharacter* spawned = nullptr;
				auto work = [&] {
					FARKDinoData data;
					data.DinoClass = cls;
					if (t.block >= 0)
						data.DinoData = cd->CustomDataBytes.ByteArrays[t.block].Bytes;
					else
					{
						data.DinoData = cd->CustomDataBytes.ByteArrays[0].Bytes;
						TArray<unsigned char>& b1 = cd->CustomDataBytes.ByteArrays[1].Bytes;
						for (int k = 0; k < b1.Num(); ++k)
							data.DinoData.Add(b1[k]);
					}
					data.DinoNameInMap = name_in_map;
					data.DinoName = shown_name;
					FVector loc = base;
					loc.Z += t.z_offset;
					FRotator rot{0, 0, 0};
					spawned = APrimalDinoCharacter::SpawnFromDinoDataEx(&data, world, &loc, &rot, &duped, team, t.new_id, nullptr, true);
				};
				const bool ok = Guarded(work);
				if (!ok)
					outcome = "crashed";
				else if (!spawned)
					outcome = duped ? "null_duped" : "null";
				else
				{
					outcome = "spawned";
					auto rec = [&] {
						result_json = "{\"summary\":" + DinoJson(spawned) + ",\n\"dino_properties\":" + PropertiesJson(spawned) + "}";
					};
					if (!Guarded(rec))
						outcome = "spawned_but_read_crashed";
					else
						success = true;
					auto kill = [&] { spawned->Destroy(false, true); };
					Guarded(kill);
				}
				attempts += std::string(attempts.size() > 1 ? "," : "") + "{\"try\":" + Q(t.label) + ",\"outcome\":" + Q(outcome) + "}";
				summary += std::string(t.label) + "=" + outcome + " ";
			}
			attempts += "]";
			if (success)
				++unpacked;
			summary += "| ";

			const std::string text = "{\"format\":\"dinodump-podtest-v2\",\"pod_label\":" + QF(shown_name) +
				",\"pod_class\":" + Q(ClassPath(cls)) + ",\n\"attempts\":" + attempts + ",\n\"result\":" + result_json +
				",\n\"pod\":" + PodJson(item, nullptr, nullptr) + ",\n\"byte_blocks\":" + blocks + "}\n";
			WriteFile(dir / ("podtest_" + std::to_string(tried) + ".json"), text);
			return tried < count;
		}, objs, items);

		const std::string m = "DinoDump podtest: " + std::to_string(unpacked) + " of " + std::to_string(tried) +
			" unpacked. " + summary + "Folder: " + dir.string();
		Log(m);
		reply(m);
	}

	// =======================================================================
	// Command plumbing
	// =======================================================================

	int ArgInt(const FString& cmd, int index, int fallback)
	{
		TArray<FString> parts;
		cmd.ParseIntoArray(parts, L" ", true);
		if (!parts.IsValidIndex(index))
			return fallback;
		try
		{
			return (std::max)(1, std::stoi(parts[index].ToString()));
		}
		catch (...)
		{
			return fallback;
		}
	}

	bool ArgHas(const FString& cmd, const std::string& word)
	{
		TArray<FString> parts;
		cmd.ParseIntoArray(parts, L" ", true);
		for (int i = 1; i < parts.Num(); ++i)
		{
			std::string p = parts[i].ToString();
			std::transform(p.begin(), p.end(), p.begin(), ::tolower);
			if (p == word)
				return true;
		}
		return false;
	}

	void Dispatch(const FString& cmd, const Reply& reply)
	{
		TArray<FString> parts;
		cmd.ParseIntoArray(parts, L" ", true);
		if (parts.Num() == 0)
			return;
		std::string name = parts[0].ToString();
		std::transform(name.begin(), name.end(), name.begin(), ::tolower);

		try
		{
			if (name == "dinodump.check")
				CmdCheck(reply);
			else if (name == "dinodump.probe")
				CmdProbe(ArgInt(cmd, 1, 3), reply);
			else if (name == "dinodump.all")
				CmdAll(ArgHas(cmd, "wild"), reply);
			else if (name == "dinodump.podtest")
				CmdPodTest(ArgInt(cmd, 1, 3), reply);
		}
		catch (const std::exception& e)
		{
			g_running = false;
			Log::GetLog()->error("DinoDump {} failed: {}", name, e.what());
			reply("DinoDump: " + name + " failed: " + e.what());
		}
	}

	void ConsoleCmd(APlayerController* pc, FString* cmd, bool)
	{
		auto* spc = static_cast<AShooterPlayerController*>(pc);
		if (!spc)
			return;
		if (!spc->bIsAdmin()())
		{
			ArkApi::GetApiUtils().SendServerMessage(spc, FColorList::Red, "{}", "DinoDump: admin only");
			return;
		}
		Dispatch(*cmd, [spc](const std::string& msg) {
			ArkApi::GetApiUtils().SendServerMessage(spc, FColorList::Green, "{}", msg);
		});
	}

	void RconCmd(RCONClientConnection* conn, RCONPacket* packet, UWorld*)
	{
		Dispatch(packet->Body, [conn, packet](const std::string& msg) {
			FString reply(msg + "\n");
			conn->SendMessageW(packet->Id, 0, &reply);
		});
	}

	// =======================================================================
	// Unattended mode
	// =======================================================================

	struct AutoCfg
	{
		bool enabled = false, wild = false, exit = false;
		int delay = 60;
	} g_auto;

	int g_auto_countdown = -1;
	bool g_auto_done = false;

	// Value after "-name=" on the launch line, quoted ("with spaces") or up to the next space.
	std::wstring ArgValue(const std::wstring& cl, const std::wstring& lower, const wchar_t* key)
	{
		const auto p = lower.find(key);
		if (p == std::wstring::npos)
			return L"";
		size_t i = p + wcslen(key);
		if (i < cl.size() && cl[i] == L'"')
		{
			const auto end = cl.find(L'"', i + 1);
			return cl.substr(i + 1, end == std::wstring::npos ? std::wstring::npos : end - i - 1);
		}
		// whole argument quoted instead: "-DinoDumpSource=Name With Spaces"
		if (p > 0 && cl[p - 1] == L'"')
		{
			const auto end = cl.find(L'"', i);
			return cl.substr(i, end == std::wstring::npos ? std::wstring::npos : end - i);
		}
		const auto end = cl.find(L' ', i);
		return cl.substr(i, end == std::wstring::npos ? std::wstring::npos : end - i);
	}

	void ReadCommandLine()
	{
		std::wstring cl = GetCommandLineW();
		std::wstring lower = cl;
		std::transform(lower.begin(), lower.end(), lower.begin(), ::towlower);
		g_auto.enabled = lower.find(L"-dinodumpauto") != std::wstring::npos;
		g_auto.wild = lower.find(L"-dinodumpwild") != std::wstring::npos;
		g_auto.exit = lower.find(L"-dinodumpexit") != std::wstring::npos;
		g_source_label = ArkApi::Tools::Utf8Encode(ArgValue(cl, lower, L"-dinodumpsource="));
		g_out_root = ArgValue(cl, lower, L"-dinodumpout=");
		const auto p = lower.find(L"-dinodumpdelay=");
		if (p != std::wstring::npos)
		{
			try
			{
				g_auto.delay = (std::max)(0, std::stoi(lower.substr(p + 15)));
			}
			catch (...)
			{
			}
		}
	}

	void OnTimer()  // every second
	{
		if (!g_auto.enabled || g_auto_done)
			return;
		if (ArkApi::GetApiUtils().GetStatus() != ArkApi::ServerStatus::Ready)
			return;
		if (g_auto_countdown < 0)
		{
			g_auto_countdown = g_auto.delay;
			Log("DinoDump: server ready, auto dump in " + std::to_string(g_auto.delay) + "s");
		}
		if (g_auto_countdown-- > 0)
			return;

		g_auto_done = true;
		CmdAll(g_auto.wild, [](const std::string& m) { Log(m); });

		if (g_auto.exit)
		{
			Log("DinoDump: -DinoDumpExit set, terminating server WITHOUT saving");
			Log::GetLog()->flush();
			TerminateProcess(GetCurrentProcess(), 0);
		}
	}

	const char* kCommands[] = {"dinodump.check", "dinodump.probe", "dinodump.all", "dinodump.podtest"};

	void Load()
	{
		Log::Get().Init("DinoDump");
		Log("DinoDump " + std::string(kPluginVersion) + " loading");

		auto& commands = ArkApi::GetCommands();
		for (const char* c : kCommands)
		{
			commands.AddConsoleCommand(FString(c), &ConsoleCmd);
			commands.AddRconCommand(FString(c), &RconCmd);
		}
		commands.AddOnTimerCallback(FString("DinoDumpAuto"), &OnTimer);

		ReadCommandLine();
		if (!g_source_label.empty())
			Log("DinoDump: source label: " + g_source_label);
		if (!g_out_root.empty())
			Log("DinoDump: output root: " + ArkApi::Tools::Utf8Encode(g_out_root));
		if (g_auto.enabled)
			Log("DinoDump: auto mode ON (delay " + std::to_string(g_auto.delay) + "s, wild " + Bool(g_auto.wild) +
				", exit " + Bool(g_auto.exit) + ")");
	}

	void Unload()
	{
		auto& commands = ArkApi::GetCommands();
		for (const char* c : kCommands)
		{
			commands.RemoveConsoleCommand(FString(c));
			commands.RemoveRconCommand(FString(c));
		}
		commands.RemoveOnTimerCallback(FString("DinoDumpAuto"));
	}

	// Field check is run once the game is up (the symbol table is loaded by then)
	void LogFieldCheck()
	{
		static bool done = false;
		if (done)
			return;
		done = true;
		CmdCheck([](const std::string& m) { Log(m); });
	}
}  // namespace DinoDump

extern "C" __declspec(dllexport) void Plugin_Init()
{
	DinoDump::Load();
	DinoDump::LogFieldCheck();
}

extern "C" __declspec(dllexport) void Plugin_Unload()
{
	DinoDump::Unload();
}
