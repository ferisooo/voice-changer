import React, { useCallback, useRef } from "react";

export type KnobProps = {
    label: string;
    value: number; // 0..100
    onChange: (value: number) => void;
    hint?: string;
};

// A small rotary "wheel" control. Drag up/down (or use the mouse wheel) to
// change the value between 0 and 100. The indicator sweeps -135deg..+135deg.
const MIN_ANGLE = -135;
const MAX_ANGLE = 135;
const DRAG_RANGE_PX = 150; // pixels of vertical drag to cover the full range

export const Knob = (props: KnobProps) => {
    const dragRef = useRef<{ startY: number; startVal: number } | null>(null);

    const clamp = (v: number) => Math.max(0, Math.min(100, Math.round(v)));

    const onPointerDown = useCallback(
        (e: React.PointerEvent<HTMLDivElement>) => {
            e.currentTarget.setPointerCapture(e.pointerId);
            dragRef.current = { startY: e.clientY, startVal: props.value };
        },
        [props.value]
    );

    const onPointerMove = useCallback(
        (e: React.PointerEvent<HTMLDivElement>) => {
            if (!dragRef.current) return;
            const dy = dragRef.current.startY - e.clientY; // up = increase
            const next = dragRef.current.startVal + (dy / DRAG_RANGE_PX) * 100;
            props.onChange(clamp(next));
        },
        [props]
    );

    const onPointerUp = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
        dragRef.current = null;
        try {
            e.currentTarget.releasePointerCapture(e.pointerId);
        } catch (_e) {
            /* ignore */
        }
    }, []);

    const onWheel = useCallback(
        (e: React.WheelEvent<HTMLDivElement>) => {
            const step = e.deltaY < 0 ? 2 : -2;
            props.onChange(clamp(props.value + step));
        },
        [props]
    );

    const onDoubleClick = useCallback(() => props.onChange(0), [props]);

    const angle = MIN_ANGLE + (clamp(props.value) / 100) * (MAX_ANGLE - MIN_ANGLE);

    return (
        <div className="eq-knob">
            <div
                className="eq-knob-dial"
                role="slider"
                aria-label={props.label}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={clamp(props.value)}
                data-tooltip-id="hint"
                data-tooltip-content={props.hint}
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onWheel={onWheel}
                onDoubleClick={onDoubleClick}
            >
                <div className="eq-knob-indicator" style={{ transform: `rotate(${angle}deg)` }}></div>
            </div>
            <div className="eq-knob-label">{props.label}</div>
            <div className="eq-knob-val">{clamp(props.value)}</div>
        </div>
    );
};
