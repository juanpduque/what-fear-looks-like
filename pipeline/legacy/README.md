# Legacy

Código y salidas superadas por versiones mejores. Se conservan como referencia
histórica del proceso (qué se intentó, por qué se descartó), no se usan en el
sitio ni en el ensayo actual.

- **`clip_typography.py`** → 8 estilos tipográficos discretos, validación débil
  (6/10). Superado por `pipeline/clip_typography_axis.py`, que mide un eje
  continuo ornate↔minimal. **Nota:** ambos scripts escriben a los mismos
  archivos (`data/typography.csv`, `data/typography_decade.json`); los que
  viven en `pipeline/data/` son los del script del eje continuo, no los de
  este script legacy.
- **`../data/legacy/faces.csv`, `../data/legacy/faces_decade.json`** →
  detección de caras con Haar cascades. Superado por `pipeline/faces_v2.py`
  (YuNet), cuya salida canónica es `data/faces_v2.csv` /
  `data/faces_v2_decade.json`.
