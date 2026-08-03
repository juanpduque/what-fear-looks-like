# Tipografía / rol del texto (equipo)

URL (después de deploy Pages):

https://juanpduque.github.io/what-fear-looks-like/label-qa-typography.html

Local: abrir `site/label-qa-typography.html`

## Clases
1. **image_led** — manda la imagen; poco o nada de lettering útil
2. **title_led** — título grande dominante (créditos chicos OK)
3. **text_heavy** — mucho copy (quotes, credits, taglines)
4. **doubtful** — no seguro

## Flujo
1. PAT fine-grained con Contents R/W en este repo (puede ser el mismo que corpus-filter / medium)
2. **Cargar desde GitHub**
3. Etiquetar (1–4)
4. **Guardar en GitHub**

Labels → `pipeline/data/qa/typography_qa_r1_labels.json`

Regen: `python3 pipeline/build_label_qa_typography.py --n 250`
