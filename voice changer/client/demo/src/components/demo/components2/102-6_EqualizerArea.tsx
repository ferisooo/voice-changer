import React, { useMemo, useState } from "react";
import { useAppState } from "../../../001_provider/001_AppStateProvider";
import { Knob } from "./102-7_Knob";

export type EqualizerAreaProps = {};

// Must mirror EQ_BAND_FREQS on the server (server/voice_changer/common/OutputFX.py).
const BAND_LABELS = ["80", "250", "1k", "4k", "12k"];
const NUM_BANDS = BAND_LABELS.length;
const BAND_MIN = -12;
const BAND_MAX = 12;

type EqProfile = { bands: number[]; bass: number; vocal: number };

const FLAT: EqProfile = { bands: [0, 0, 0, 0, 0], bass: 0, vocal: 0 };

// bands are dB (-12..12), bass/vocal are 0..100.
const PRESETS: { [name: string]: EqProfile } = {
    Flat: FLAT,
    "Bass Boost": { bands: [6, 3, 0, 0, 0], bass: 70, vocal: 0 },
    "Vocal Boost": { bands: [-2, 0, 2, 4, 1], bass: 0, vocal: 70 },
    Bright: { bands: [0, 0, 1, 4, 6], bass: 0, vocal: 20 },
    Warm: { bands: [4, 3, 0, -2, -3], bass: 40, vocal: 0 },
    Kawaii: { bands: [-3, -1, 2, 5, 7], bass: 0, vocal: 60 },
};
const CUSTOM = "Custom";

const parseProfile = (raw: string | undefined): EqProfile => {
    if (!raw) return { ...FLAT, bands: [...FLAT.bands] };
    try {
        const p = JSON.parse(raw);
        const bands = Array.from({ length: NUM_BANDS }, (_, i) => {
            const v = Number(p?.bands?.[i]);
            return Number.isFinite(v) ? v : 0;
        });
        return {
            bands,
            bass: Number.isFinite(Number(p?.bass)) ? Number(p.bass) : 0,
            vocal: Number.isFinite(Number(p?.vocal)) ? Number(p.vocal) : 0,
        };
    } catch (_e) {
        return { ...FLAT, bands: [...FLAT.bands] };
    }
};

const isFlat = (p: EqProfile): boolean => p.bands.every((b) => b === 0) && p.bass === 0 && p.vocal === 0;

const matchPreset = (p: EqProfile): string => {
    for (const [name, preset] of Object.entries(PRESETS)) {
        if (preset.bass === p.bass && preset.vocal === p.vocal && preset.bands.every((b, i) => b === p.bands[i])) {
            return name;
        }
    }
    return CUSTOM;
};

export const EqualizerArea = (_props: EqualizerAreaProps) => {
    const { serverSetting } = useAppState();
    const [presetName, setPresetName] = useState<string>("");

    const equalizerArea = useMemo(() => {
        if (!serverSetting.updateServerSettings || !serverSetting.serverSetting) {
            return <></>;
        }

        const profile = parseProfile(serverSetting.serverSetting.eqProfile);
        // Keep the dropdown in sync with whatever profile is actually active.
        const effectivePreset = presetName || matchPreset(profile);

        const writeProfile = (next: EqProfile, preset: string) => {
            setPresetName(preset);
            const eqProfile = isFlat(next) ? "" : JSON.stringify(next);
            serverSetting.updateServerSettings({ ...serverSetting.serverSetting, eqProfile });
        };

        const onPresetChange = (name: string) => {
            const preset = PRESETS[name];
            if (!preset) {
                setPresetName(name);
                return;
            }
            writeProfile({ bands: [...preset.bands], bass: preset.bass, vocal: preset.vocal }, name);
        };

        const onBandChange = (index: number, value: number) => {
            const bands = [...profile.bands];
            bands[index] = value;
            writeProfile({ ...profile, bands }, CUSTOM);
        };

        const presetSelect = (
            <div className="config-sub-area-control">
                <div className="config-sub-area-control-title">
                    <a className="hint-text" data-tooltip-id="hint" data-tooltip-content="Equalizer preset. Pick one or tweak the sliders/knobs for a custom curve.">
                        PRESET
                    </a>
                    :
                </div>
                <div className="config-sub-area-control-field">
                    <select className="body-select" value={effectivePreset} onChange={(e) => onPresetChange(e.target.value)}>
                        {Object.keys(PRESETS).map((name) => (
                            <option key={name} value={name}>
                                {name}
                            </option>
                        ))}
                        {effectivePreset === CUSTOM && (
                            <option key={CUSTOM} value={CUSTOM}>
                                {CUSTOM}
                            </option>
                        )}
                    </select>
                </div>
            </div>
        );

        const bandSliders = (
            <div className="eq-bands">
                {profile.bands.map((gain, i) => (
                    <div className="eq-band" key={i}>
                        <div className="eq-band-val">{gain > 0 ? `+${gain}` : gain}</div>
                        <input
                            className="eq-band-slider"
                            type="range"
                            min={BAND_MIN}
                            max={BAND_MAX}
                            step={1}
                            value={gain}
                            onChange={(e) => onBandChange(i, Number(e.target.value))}
                            onDoubleClick={() => onBandChange(i, 0)}
                        />
                        <div className="eq-band-label">{BAND_LABELS[i]}</div>
                    </div>
                ))}
            </div>
        );

        const knobs = (
            <div className="eq-knobs">
                <Knob label="Bass" value={profile.bass} hint="Bass boost. Adds low-end warmth and punch." onChange={(v) => writeProfile({ ...profile, bass: v }, CUSTOM)} />
                <Knob label="Vocal" value={profile.vocal} hint="Vocal boost. Lifts presence so the voice cuts through." onChange={(v) => writeProfile({ ...profile, vocal: v }, CUSTOM)} />
            </div>
        );

        return (
            <div className="config-sub-area">
                <div className="config-sub-area-control-title-long">Equalizer</div>
                {presetSelect}
                <div className="eq-controls">
                    {bandSliders}
                    {knobs}
                </div>
            </div>
        );
    }, [serverSetting.serverSetting, serverSetting.updateServerSettings, presetName]);

    return equalizerArea;
};
