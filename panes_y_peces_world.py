#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
  PANES Y PECES (WORLD)  -  Generador de muestras de wake word
  Motor: WORLD vocoder  ->  pitch y FORMANTES por separado (voces mas naturales)
==============================================================================
Igual que panes_y_peces.py pero usando el vocoder WORLD (pyworld) en vez de
rubberband. WORLD descompone la voz en 3 componentes independientes:
    - F0  : el tono (pitch)
    - SP  : la envolvente espectral = LOS FORMANTES (el "timbre", tamano de garganta)
    - AP   : aperiodicidad (la parte de "aire"/ruido de la voz)
Manipulando SP (formantes) por separado del F0 (pitch) se consiguen voces de
nino/mujer/viejo mucho mas creibles, sin el efecto "ardilla" del pitch a secas.

USO:
    python3 panes_y_peces_world.py ./entrada ./salida

DEPENDENCIAS:
    pip install soundfile pyworld numpy --break-system-packages
    (no necesita rubberband; WORLD hace todo)
"""
import sys, os, glob
import numpy as np
import soundfile as sf
import pyworld as pw

SR = 16000

# -----------------------------------------------------------------------------
# TABLA DE TIMBRES  (motor WORLD)
#   pitch_factor : multiplica el F0. 1.0=igual, >1 mas agudo, <1 mas grave
#                  (1.5 aprox = una octava arriba de mujer/nino)
#   formant_warp : deforma la envolvente espectral (formantes).
#                  >1 = garganta MAS PEQUENA (nino), <1 = garganta MAS GRANDE (grave)
#                  Este es el parametro que "calca" el timbre de verdad.
#   tempos       : factores de velocidad
# -----------------------------------------------------------------------------
TIMBRES = {
    "voz_normal": {"pitch": 1.00, "warp": 1.00, "tonos": {
                        "agudo": 1.18, "normal": 1.00, "grave": 0.85},
                    "tempos": {"rapido": 1.25, "normal": 1.0, "lento": 0.87}},
    "nino":       {"pitch": 1.45, "warp": 1.22,
                    "tempos": {"rapido": 1.22, "normal": 1.0, "lento": 0.90}},
    "mujer":      {"pitch": 1.30, "warp": 1.12,
                    "tempos": {"rapido": 1.20, "normal": 1.0, "lento": 0.90}},
    "hombre":     {"pitch": 0.82, "warp": 0.92,
                    "tempos": {"rapido": 1.20, "normal": 1.0, "lento": 0.90}},
    "viejo":      {"pitch": 0.78, "warp": 0.95, "temblor": True,
                    "tempos": {"normal": 1.0, "lento": 0.85}},
}

# -----------------------------------------------------------------------------
def cargar_mono_16k(path):
    audio, sr = sf.read(path)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        # remuestreo simple por interpolacion lineal
        n = int(round(len(audio) * SR / sr))
        audio = np.interp(np.linspace(0, len(audio), n, endpoint=False),
                          np.arange(len(audio)), audio)
    return np.ascontiguousarray(audio, dtype=np.float64)

def warp_formantes(sp, factor):
    """Estira o comprime la envolvente espectral en frecuencia = mueve formantes.
       factor>1 sube los formantes (garganta pequena=nino);
       factor<1 los baja (garganta grande=grave)."""
    n_bins = sp.shape[1]
    src = np.arange(n_bins)
    # posicion origen para cada bin destino (warp lineal en frecuencia)
    warped = np.clip(src / factor, 0, n_bins - 1)
    out = np.empty_like(sp)
    for t in range(sp.shape[0]):
        out[t] = np.interp(warped, src, sp[t])
    return out

def aplicar_temblor(audio, sr=SR, hz=5.0, prof=0.03):
    t = np.arange(len(audio)) / sr
    return audio * (1.0 + prof * np.sin(2*np.pi*hz*t))

def transformar(audio, pitch_factor, warp, tempo, temblor=False):
    x = np.ascontiguousarray(audio, dtype=np.float64)
    # 1) Analisis WORLD: descompone en F0, envolvente espectral (SP) y aperiodicidad (AP)
    f0, t = pw.harvest(x, SR)
    sp = pw.cheaptrick(x, f0, t, SR)
    ap = pw.d4c(x, f0, t, SR)
    # 2) PITCH: escalar el F0 (solo donde hay voz, f0>0)
    f0_mod = f0 * pitch_factor
    # 3) FORMANTES: deformar la envolvente espectral por separado del pitch
    if abs(warp - 1.0) > 1e-3:
        sp = warp_formantes(sp, warp)
    # 4) Sintesis
    y = pw.synthesize(f0_mod, sp, ap, SR)
    # 5) TEMPO: estirar/acortar por remuestreo (cambia duracion, no el pitch ya fijado)
    if abs(tempo - 1.0) > 1e-3:
        n = int(round(len(y) / tempo))
        y = np.interp(np.linspace(0, len(y), n, endpoint=False),
                      np.arange(len(y)), y)
    if temblor:
        y = aplicar_temblor(y)
    m = np.max(np.abs(y)) or 1.0
    return (y / m * 0.9).astype(np.float32)

def main():
    if len(sys.argv) < 3:
        print("Uso: python3 panes_y_peces_world.py <entrada> <salida>")
        sys.exit(1)
    ent, sal = sys.argv[1], sys.argv[2]
    os.makedirs(sal, exist_ok=True)
    registros = sorted(glob.glob(os.path.join(ent, "*.wav")))
    if not registros:
        print(f"No hay .wav en {ent}."); sys.exit(1)

    total = 0
    print(f"Registros encontrados: {len(registros)}  (motor: WORLD vocoder)")
    for reg_path in registros:
        reg = os.path.splitext(os.path.basename(reg_path))[0]
        audio = cargar_mono_16k(reg_path)
        print(f"\n[{reg}] procesando...")
        for tname, tcfg in TIMBRES.items():
            temblor = tcfg.get("temblor", False)
            tonos = tcfg.get("tonos", {"": 1.0})
            for toname, tono_extra in tonos.items():
                for veloname, tempo in tcfg["tempos"].items():
                    pitch = tcfg["pitch"] * tono_extra
                    y = transformar(audio, pitch, tcfg["warp"], tempo, temblor)
                    partes = [reg, tname]
                    if toname: partes.append(toname)
                    partes.append(veloname)
                    sf.write(os.path.join(sal, "_".join(partes) + ".wav"), y, SR, subtype="PCM_16")
                    total += 1
        print(f"   -> generadas para [{reg}]")
    print(f"\n==== LISTO: {total} muestras en {sal} (motor WORLD) ====")
    print(f"   ({len(registros)} registros -> {total} ficheros)")

if __name__ == "__main__":
    main()
