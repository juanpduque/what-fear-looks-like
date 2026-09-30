(function () {
  const REDUCE = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const IMG = "https://image.tmdb.org/t/p/w185";
  const HALLOWEEN = "images/halloween.jpg";
  const PATHS = {
    136: "/fX2Wxd0W9E7eVClUd8kJTfennoV.jpg",
    170: "/sQckQRt17VaWbo39GIu0TMOiszq.jpg",
    348: "/vfrQk5IPloGg1v9Rzbh2Eg3VGyM.jpg",
    377: "/wGTpGGRMZmyFCcrY2YoxVTIBlli.jpg",
    565: "/e2t5CKMox7tjv3iD3Ko7NdFa5lJ.jpg",
    571: "/z0iYrJ6GsAMP3abOha7uGMuc5kZ.jpg",
    578: "/lxM6kqilAdpdhqUl2biYp5frUxE.jpg",
    653: "/zv7J85D8CC9qYagAEhPM63CIG6j.jpg",
    694: "/nRj5511mZdTl4saWEPoj9QroTIu.jpg",
    805: "/s8pdaHjxNPLXIA1WjSTWm00RJTz.jpg",
    831: "/2viRDpHmhzQoreZok2auLjkVbSE.jpg",
    948: "/qVpCaBcnjRzGL3nOPHi6Suy0sB6.jpg",
    1091: "/tzGY49kseSE9QAKk47uuDGwnSCu.jpg",
    1678: "/ixfHV61iRM4Jkgw0uI5ICtNwfmX.jpg",
    1946: "/kETKF0JhdTPn1knci8CAdYL0d79.jpg",
    3053: "/iH8Ohx97F2eIagrJGzCEraO93MN.jpg",
    3076: "/eitxewmvmZXY7qoKpiVhdaFmwMz.jpg",
    4283: "/5ou56J8FIxbIFusR9zIA9GW7zwt.jpg",
    4488: "/HzrPn1gEHWixfMOvOehOTlHROo.jpg",
    4970: "/frSGNQcWx1ek8dCduFYCux1ho7n.jpg",
    9841: "/1qAQWKjfAgxQN4atIMWnssBWHOf.jpg",
    9980: "/cFrKCumtZMHCWwWNxgGRyaxhYu2.jpg",
    10065: "/4D246dpe7yy2GvHI2IbpeqkUXry.jpg",
    10493: "/hXpav86ZX5N1YIfVfVtzuZLNrjW.jpg",
    10676: "/4qDtn4RNIEY4OgitIxi3P1CtthO.jpg",
    10973: "/aGM3tYt0r2NO4Uc8dNEbAMhXeEk.jpg",
    11470: "/jrObEGWVW1XlutjYXqyyGxtTeov.jpg",
    11549: "/wVXt7h98sTKhLjq1TdvdGwdyJo8.jpg",
    11586: "/g9i3LTMYLRHvCYSKimZEfd1Vqy7.jpg",
    11815: "/kXdBcDh2EbgSIf4Oo1dxKapZM2f.jpg",
    11868: "/1L45hwUu1P4NRhbRRrE5d9oHamm.jpg",
    15360: "/dij60cVBL39B5t1SdGQr33APksC.jpg",
    15849: "/vSKpbZVvzqQcw6htiyEinbCY9vq.jpg",
    16028: "/nHG0VOW6o99tP5EACtKTMADqxJQ.jpg",
    16281: "/4SoyTCEpsgLjX6yAyMsx3AsAyRQ.jpg",
    18498: "/yV8z6deULhH4oJAUj2YdhITPwfc.jpg",
    18983: "/19RDmhX6LtzMxv0KXXAU1IBIvvA.jpg",
    21588: "/cI5AV3jCuxmoQp0N7Z16SI2b7Xk.jpg",
    23439: "/jEzZOrGSWpl0jKOIXoY3OnEabLQ.jpg",
    24198: "/46whh6JCDqRFxHfKssePScUvD8D.jpg",
    28046: "/dmMBlNiGLQJRVNGgy8SRnscidUn.jpg",
    28532: "/A17gEQk617FsLhtPyalRN885KM3.jpg",
    28659: "/uecOR4c3IrZ2AusokpyifrtJks9.jpg",
    28774: "/5WsMyE6wwY2QbM3fpAePOX3e7pZ.jpg",
    29077: "/a5cCwJEnVSPtTqHgIE9UxHIoWFl.jpg",
    29748: "/3xMrdNnyvYrdJaKq9dWJKkTHGvP.jpg",
    31592: "/t4058MoAiVg8R1aqHNL3nAP48km.jpg",
    31682: "/1Tl2aeOhvUmEHSGHGH5SfmN19vQ.jpg",
    35911: "/ypQ7rC8lUgt9g7yAMmmfq5vx0Fo.jpg",
    38299: "/2tP5jkSJ8Nu3OsIQLaCEktepOLp.jpg",
    39259: "/vXpPf8MFLqp4f9KdUyjL7tSYDmd.jpg",
    39995: "/p9S9UuYA4uHdoH9FecB3sU9zpfm.jpg",
    43115: "/4uns8WSxu9LSFv0FkJP8uv6Q5kQ.jpg",
    45803: "/jLE87vAc9bqytSZAfU76MmnQdMh.jpg",
    45878: "/glZ0Wz5u2Vr7TzM6Kj1f4e6EliU.jpg",
    46767: "/64rlKmchkFyLDh6XP2XqPHw9nPd.jpg",
    48885: "/eHzJBkfEV4fUVxAfspt1jOxBIc.jpg",
    49183: "/njSWFPeTaZYoKKeuyf1Ga6OYAuh.jpg",
    50606: "/mPH3YLnyU5qT7FUMd1U1wWD41Ep.jpg",
    52199: "/yZHinX5xzbkhXvX5t4lxKuDQEHQ.jpg",
    54653: "/bjVqT8XIVMTCWpSreMpH0W6Rjxi.jpg",
    58129: "/vmhMEj2d8JnKS5jzqJf4kYypKWN.jpg",
    59189: "/zeM6HitVufjH9nvWvg4MraucwzU.jpg",
    60086: "/7DQlbb4ax5L5NZvMjr54KOsXGyF.jpg",
    70772: "/zVK76DDtIKdIiRRraAVrsyek04t.jpg",
    72153: "/bLYZAd3yukk9HFamT16XHFrmKtw.jpg",
    73336: "/ztg12ZJK2Vi8tHl9vsNxFJ1hc4A.jpg",
    74915: "/2CafSu1hxvxLRYTiFuhA3sH0xNP.jpg",
    84712: "/ebytaLUSQSYSUrDUVako5rln7t7.jpg",
    84713: "/5GnQ6Sao5NITgRJmnrCFbZUljBm.jpg",
    85498: "/xlfJKdjwUZNfT2QUEUv0RozVuEs.jpg",
    88353: "/f7IxkjIQWDiVgrUmkfA3HYljuJF.jpg",
    93929: "/vjpqjUYOS9Nv2nEkNuo2UoNdtPv.jpg",
    117429: "/fQ4xCUh2sL3B5EqTXoLHn9uAnGN.jpg",
    127642: "/4tSMIUeLYGQFeBnHgS7TVuYiAi0.jpg",
    138017: "/q63uhDxhJgavt5FwhyMtaljPhA.jpg",
    141442: "/2oBgGXtsh2GvnBesUAqlHvf5Q7P.jpg",
    145850: "/2nPPxIb8Rlbwvs4HsjOmZsa2QlE.jpg",
    147087: "/Aeae33Ng1ZUIcVgbuosFxsxVt0y.jpg",
    150196: "/tvWuDc0a7230xduESz3R6lJlbEr.jpg",
    156068: "/qObcGnlli4zlCc99DpTQv95GBZy.jpg",
    212005: "/dRKpOGEJLLnD0QYFn8ku4DBYwGz.jpg",
    226630: "/y3j0wddj5U6W9ZBL8NxPQOxLgJo.jpg",
    279690: "/vzqwe4uuINJhbPqvlbVShBnCvHv.jpg",
    310131: "/zap5hpFCWSvdWSuPGAQyjUv2wAC.jpg",
    329237: "/6YcIEhXzMSuNdrooBUsO3mZK8rT.jpg",
    332567: "/42HlPJmiE6rQdtT2lYzPPMQYvqG.jpg",
    345940: "/xqECHNvzbDL5I3iiOVUkVPJMSbc.jpg",
    363059: "/f0waM4gnQyfdsduQgukVRBQ9Pkn.jpg",
    416753: "/gVBUEYI8eIaFZZv5BR6DPVuJZsS.jpg",
    419479: "/86a7GRVRCwfl7wdI4QadyvKa6Zu.jpg",
    425972: "/cdPSUck4tBRvRu6DFk6XciDrssn.jpg",
    439917: "/soP8q3FtbTseRVcJavkXDuhVFac.jpg",
    460458: "/7uRbWOXxpWDMtnsd2PF3clu65jc.jpg",
    476299: "/tt9YSQlArAj6849SQQJ5ryNgcJs.jpg",
    495447: "/stTZqv11cqWOZbTySSpf6ciDnr2.jpg",
    519418: "/pNrdzyE39G6brgCF1YmrW73aecy.jpg",
    535412: "/sPEh50GkEO3mTMdwn3Dz1LjEp9h.jpg",
    564446: "/1c9os1zQi5X0hey7J9PKGBGFYHm.jpg",
    575869: "/gkDW017O3DLK9vBMEcAMSunnuo9.jpg",
    591275: "/rmEPtz3Ufzol2VWUAZYzOFaBio3.jpg",
    751423: "/gTOl98Sqie5pDxomspvWLXN66BJ.jpg",
    875138: "/6MPBRoFpEWpohhKZqT19q62U8If.jpg",
    882598: "/hiaeZKzwsk4y4atFhmncO5KRxeT.jpg",
    883891: "/gpXdkzoens2K8VtVaMORem9f95.jpg",
    1266263: "/nzH5kkXIHd7BGTXqAWVW4WLAdnm.jpg"
  };

  function posterSrc(id) {
    if (PATHS[id]) return IMG + PATHS[id];
    return "../assets/posters/" + id + ".jpg";
  }

  const I18N = {
    skip: { es: "Saltar al contenido", en: "Skip to content" },
    kicker: { es: "Un análisis de afiches", en: "A poster analysis" },
    title: { es: 'Cómo se ve<br><span class="blood">el miedo</span>', en: 'What <span class="blood">Fear</span><br>Looks Like' },
    dek: {
      es: "Medimos color, oscuridad, rostros y criaturas en <strong>37,829 afiches</strong> de 1897 a 2028.",
      en: "We measured color, darkness, faces and creatures across <strong>37,829 posters</strong> from 1897 to 2028.",
    },
    byline: {
      es: "Por <b>Juan Pablo Duque</b> · Pulp Analytics · octubre 2026",
      en: "By <b>Juan Pablo Duque</b> · Pulp Analytics · October 2026",
    },
    scroll: {
      es: 'Baja si te atreves <span class="sc-arrow" aria-hidden="true">↓</span>',
      en: 'Scroll if you dare <span class="sc-arrow" aria-hidden="true">↓</span>',
    },
    nav_spec: { es: "espécimen", en: "specimen" },
    nav_acts: { es: "actos", en: "acts" },
    nav_eras: { es: "eras", en: "eras" },
    nav_cara: { es: "cara a cara", en: "face to face" },
    rail_color: { es: "Color", en: "Color" },
    rail_dark: { es: "Luz", en: "Light" },
    rail_blood: { es: "Rojo", en: "Red" },
    rail_faces: { es: "Rostro", en: "Face" },
    rail_quiet: { es: "Voz", en: "Voice" },
    rail_type: { es: "Tipo", en: "Type" },
    i1: { es: "Un día estaba en Netflix buscando una película de terror. Y algo me hizo click.", en: "I was scrolling Netflix one day looking for a horror movie. And something hit me." },
    i2: { es: "Los pósters se veían distintos a lo que recordaba.", en: "The posters looked different from what I remembered." },
    i3: { es: "Cuando alquilaba terror en VHS, las cajas te gritaban. Colores vivos. Caras enormes. Rojo sangre. Tenías dos segundos para decidir. El afiche era toda la venta.", en: "Back when I rented horror on VHS, the boxes screamed at you. Bright colors. Big faces. Blood red. You had two seconds to decide. The poster was the whole pitch." },
    i4: { es: "¿Y ahora? Los nuevos se ven callados. Oscuros. A veces solo negro con una palabra. Sin caras. Sin colores. Nada que llame la atención.", en: "But now? The new sheets look quiet. Dark. Sometimes just black with one word. No faces. No colors. Nothing jumping out." },
    i5: { es: "Así que empecé a preguntarme: ¿cuándo dejó el terror de gritar?", en: "So I started wondering: when did horror stop shouting?" },
    i6: { es: "Decidí averiguarlo. Bajé <strong>37,829 afiches de terror</strong> — desde 1897 hasta 2028 — y los medí. Lo que encontré es raro: el terror no se volvió más aterrador. Bajó la voz.", en: "I decided to find out. I pulled <strong>37,829 horror posters</strong> — from 1897 all the way to 2028 — and I measured them. What I found is weird: horror didn't get scarier. It got quieter." },
    about_k: { es: "Sobre los datos", en: "About the data" },
    about_p: { es: "De los ~72,000 títulos de terror en TMDB me quedé con <strong>37,829</strong> afiches en inglés con arte usable — 1897 a 2028. Solo inglés, sin Animación, sin Música. Luego medí cada uno igual.", en: "From TMDB's ~72,000 Horror titles I kept <strong>37,829</strong> English-language posters with usable art — 1897 to 2028. English only, no Animation, no Music. Then I measured every sheet the same way." },
    spec_k: { es: "El espécimen", en: "The specimen" },
    spec_h: { es: "Halloween, 1978", en: "Halloween, 1978" },
    spec_tag: { es: "Una pesadilla, medida dos veces", en: "One nightmare, measured twice" },
    spec_p: { es: "Antes del siglo entero, una sola hoja: quizá el afiche de terror más imitado. Vacío negro. Una mano. Un cuchillo. Una calabaza. Cero rostros humanos. Las mismas seis medidas que corremos en los 37,829.", en: "Before the whole century, one sheet: maybe the most imitated horror poster ever printed. Black void. A hand. A knife. A pumpkin. Zero human faces. The same six measurements we run on all 37,829." },
    spec_s1: { es: "<b>72%</b> negro", en: "<b>72%</b> black" },
    spec_s2: { es: "rojo sangre <b>11%</b>", en: "blood-red <b>11%</b>" },
    spec_s3: { es: "<b>0</b> rostros humanos · la calabaza se lee como cráneo", en: "<b>0</b> human faces · the pumpkin reads as a skull" },
    spec_s4: { es: "una gran palabra arriba", en: "one big word on top" },
    spec_hint: { es: "Baja — las seis medidas viven en esta hoja →", en: "Scroll — the six measurements live on this sheet →" },
    spec_ov1: { es: "72% negro", en: "72% black" },
    spec_ov2: { es: "rojo sangre 11%", en: "blood-red 11%" },
    spec_ov3: { es: "0 rostros · calabaza = cráneo", en: "0 faces · pumpkin = skull" },
    spec_ov4: { es: "½ del brillo de 1978", en: "½ as bright as 1978" },
    spec_ov5: { es: "una gran palabra arriba", en: "one big word on top" },
    spec_ov6: { es: "el nombre es el afiche", en: "the name is the poster" },
    spec_b1_k: { es: "01 · Oscuridad", en: "01 · Darkness" },
    spec_b1_h: { es: "Negro", en: "Black" },
    spec_b1_p: { es: "Casi tres cuartos de la hoja. Un cuchillo. Una calabaza. El resto es vacío.", en: "Almost three-quarters of the sheet. A knife. A pumpkin. The rest is void." },
    spec_b2_k: { es: "02 · Rojo", en: "02 · Red" },
    spec_b2_h: { es: "Sangre como acento", en: "Blood as accent" },
    spec_b2_p: { es: "No es un diluvio. Es un corte: la calabaza y el título, no el fondo.", en: "Not a flood. A cut: the pumpkin and the title, not the ground." },
    spec_b3_k: { es: "03 · Rostros", en: "03 · Faces" },
    spec_b3_h: { es: "Cero caras humanas", en: "Zero human faces" },
    spec_b3_p: { es: "La calabaza se lee como cráneo. El monstruo no necesita ojos.", en: "The pumpkin reads as a skull. The monster doesn't need eyes." },
    spec_b4_k: { es: "04 · Luz", en: "04 · Light" },
    spec_b4_h: { es: "Más oscura que su año", en: "Darker than its year" },
    spec_b4_p: { es: "Menos de la mitad del brillo medio de 1978. Iba años adelantada.", en: "Less than half as bright as the 1978 average. Years ahead of the genre." },
    spec_b5_k: { es: "05 · Voz", en: "05 · Voice" },
    spec_b5_h: { es: "Una palabra arriba", en: "One word on top" },
    spec_b5_p: { es: "HALLOWEEN a 15 metros. El estante de videoclub no perdona.", en: "HALLOWEEN from 15 meters. The video-store shelf does not forgive." },
    spec_b6_k: { es: "06 · Letraje", en: "06 · Lettering" },
    spec_b6_h: { es: "El nombre es el afiche", en: "The name is the poster" },
    spec_b6_p: { es: "Las mismas seis medidas del siglo, en una sola caja. Ahora sí, el río.", en: "The same six measurements of the century, on one sleeve. Now the river." },
    c_k: { es: "Parte I · Río de color", en: "Part I · Color river" },
    c_h: { es: "El negro se tomó el afiche", en: "Black took the sheet" },
    c_tag: { es: "1950s cálidos → diluvio negro", en: "Warm 1950s → black flood" },
    c_p: { es: "En los 50 el terror era rojo, naranja, calor pulp. Luego todo se volvió negro. Los 80 tienen un destello de azul neón. No dura. Gana el negro. Los colores cálidos nunca vuelven en serio.", en: "In the 1950s, horror was warm — red, orange, pulp heat. Then everything turned black. The '80s get a blue neon flash. It doesn't last. Black wins. The warm colors never really come back." },
    c_n: { es: "n = 37,829 · cuota media de píxeles por década", en: "n = 37,829 · mean pixel share per decade" },
    c_more: { es: "Mostrar las 6 familias", en: "Show all 6 hue families" },
    d_k: { es: "Parte II · Oscuridad", en: "Part II · Darkness" },
    d_h: { es: "La luz nunca volvió", en: "The light never came back" },
    d_tag: { es: "Una montaña, no un tobogán", en: "A mountain, not a slide" },
    d_p: { es: "El brillo sube hasta un pico alrededor de 1960 — era atómica, «¡MIRA! ¡ATERRADOR!» — y después el terror baja sesenta años seguidos. Sin rebote.", en: "Brightness climbs to a daylight peak around 1960 — atomic age, SEE! SHOCKING! — then horror descends for sixty years straight. No rebound." },
    d_n: { es: "n = 37,829 · brillo medio L* · media móvil 5 años", en: "n = 37,829 · mean L* brightness · 5-yr rolling mean" },
    b_k: { es: "Parte III · Rojo y sangre", en: "Part III · Red & blood" },
    b_h: { es: "El rojo llegó después de los slashers", en: "Red peaked after the slashers" },
    b_tag: { es: "El pico no es 1980", en: "The peak is not 1980" },
    b_p: { es: "Uno pensaría que los slashers son dueños del rojo. No lo son. El pico real es el giro del milenio. Y rojo no es lo mismo que sangre: después de los 80 las dos medidas se separan.", en: "You'd think the '80s slashers owned red. They didn't. The real peak is the turn of the millennium. And red isn't blood: after the slashers the two measures split." },
    b_n: { es: "Rojo-píxel vs sangre semántica CLIP · n = 37,829", en: "Pixel-red vs CLIP semantic blood · n = 37,829" },
    f_k: { es: "Parte IV · Rostros y monstruos", en: "Part IV · Faces & monsters" },
    f_h: { es: "El rostro se retira. El fantasma regresa.", en: "The face retreats. The ghost returns." },
    f_tag: { es: "1945: 87% · hoy: < 50%", en: "1945: 87% · today: < 50%" },
    f_p: { es: "En los 40 la mirada era casi obligatoria. Hoy menos de la mitad de las hojas tienen un rostro. El siglo empieza y termina con el fantasma. El trono del monstruo cambia de manos.", en: "In the 1940s that stare was nearly mandatory. Today fewer than half the sheets have a face. The century begins and ends with the ghost. The monster's throne keeps changing hands." },
    f_n: { es: "YuNet · CLIP vs 18 criaturas · n = 37,829", en: "YuNet · CLIP vs 18-creature taxonomy · n = 37,829" },
    q_k: { es: "Parte V · El silencio", en: "Part V · The quieting" },
    q_h: { es: "El terror bajó la voz", en: "Horror lowered its voice" },
    q_tag: { es: "Grito ~34% → ~18%", en: "Shout ~34% → ~18%" },
    q_p: { es: "Estante de los 50: letras que GRITAN a 15 metros. Miniatura de Netflix: una palabra delgada. El volumen bajó porque bajó la distancia. Debajo, dos huellas más: simetría que salta después de 2010, y composiciones que dejaron de inclinarse.", en: "A 1950s shelf: letters SHOUTING from 50 feet. A Netflix thumbnail: one thin word. The volume dropped because the distance did. Below, two more fingerprints: symmetry leaping after 2010, and compositions that stopped leaning." },
    q_n: { es: "MSER cobertura similar a texto · n = 37,829", en: "MSER text-like coverage · n = 37,829" },
    q_sym: { es: "Simetría espejo", en: "Mirror symmetry" },
    q_diag: { es: "Score diagonal", en: "Diagonal score" },
    q_method: { es: "Ver cajas MSER y pliegues →", en: "See MSER boxes and folds →" },
    t_k: { es: "Parte VI · Letraje", en: "Part VI · Lettering" },
    t_h: { es: "El miedo dejó de gritar su nombre", en: "Fear stopped shouting its name" },
    t_tag: { es: "1940s ornate 71% → 2020s minimal 27%", en: "1940s ornate 71% → 2020s minimal 27%" },
    t_p: { es: "En los 40, letras ornamentadas de exhibición. Apenas 4% minimalistas. En los 2020 se invirtió: lo ornamentado se volvió «barato», lo minimalista «elevado».", en: "In the 1940s, ornate display lettering. Barely 4% were minimal. By the 2020s that flipped — ornate became “cheap,” minimal became “elevated.”" },
    t_n: { es: "Eje ornate↔minimal CLIP · n = 37,829", en: "CLIP ornate↔minimal axis · n = 37,829" },
    e0: { es: "Retratos pintados. El monstruo era la película. Hojas oscuras, letraje ornamentado. Seis disfraces de la misma retirada.", en: "Painted portraits. The monster WAS the movie. Six costumes of the same retreat." },
    e1: { es: "El grito del autocinema. La era más brillante. Un rostro era casi obligatorio.", en: "Drive-in shout. The brightest era. A face was nearly mandatory." },
    e2: { es: "El monstruo se muda a la casa de al lado. Las luces empiezan a bajar.", en: "The monster moves in next door. The lights start dimming." },
    e3: { es: "El cuchillo como logo. Guerra de estantes VHS. Los slashers no son dueños del pico del rojo.", en: "The knife as logo. VHS shelf war. Slashers do not own red's peak." },
    e4: { es: "Meta-terror. El pico de verdad del rojo. La sangre se vuelve un lenguaje.", en: "Meta-horror. Red's real peak. Blood becomes a language." },
    e5: { es: "Terror elevado. Una palabra delgada sobre negro. El fantasma vuelve al trono.", en: "Elevated horror. One thin word on black. The ghost returns to the throne." },
    cara_k: { es: "Dos eras, cinco medidas", en: "Two eras, five measures" },
    cara_h: { es: "Cara a cara", en: "Face to face" },
    cara_p: { es: "Elige dos años. El mayor de cada fila se pinta en rojo sangre.", en: "Pick two years. The larger number in each row is painted blood red." },
    pick_a: { es: "Era A", en: "Era A" },
    pick_b: { es: "Era B", en: "Era B" },
    close_k: { es: "Cierre", en: "Close" },
    close_h: { es: "El miedo tiene un rostro de un siglo", en: "Fear has a century-long face" },
    close_p: { es: "Y ha estado bajando la voz desde que aprendimos a escuchar la oscuridad.", en: "And it's been getting quieter ever since we learned to listen to the dark." },
    close_2: { es: "Los afiches no mienten. Te cuentan todo sobre qué nos asustó, cuándo y por qué. Solo tienes que saber cómo leerlos.", en: "The posters don't lie. They tell you everything about what scared us, when, and why. All you have to do is know how to read them." },
    link_essay: { es: "El ensayo con gráficos", en: "The charts essay" },
    link_lookup: { es: "Disecciona cualquier póster", en: "Dissect any poster" },
    illust: { es: "Las ilustraciones son originales — no son afiches de estudio.", en: "Illustrations are original — not studio posters." },
    method: { es: "Cómo se midió →", en: "How it was measured →" },
    cmp_shout: { es: "Grito (texto %)", en: "Shout (text %)" },
    cmp_bright: { es: "Brillo (L*)", en: "Brightness (L*)" },
    cmp_faces: { es: "Rostros %", en: "Faces %" },
    cmp_red: { es: "Rojo sangre %", en: "Blood-red %" },
    cmp_blood: { es: "Sangre semántica %", en: "Semantic blood %" },
    g_shout: { es: "Grito · texto MSER", en: "Shout · MSER text" },
    g_bright: { es: "Brillo · L*", en: "Brightness · L*" },
    g_faces: { es: "Rostros %", en: "Faces %" },
    g_red: { es: "Rojo-píxel %", en: "Pixel-red %" },
    g_blood: { es: "Sangre semántica %", en: "Semantic blood %" },
    g_dark: { es: "Río oscuro %", en: "Dark river %" },
    g_ornate: { es: "Letraje ornate %", en: "Ornate lettering %" },
    lab_pixel: { es: "Rojo-píxel", en: "Pixel-red" },
    lab_sem: { es: "Sangre semántica", en: "Semantic blood" },
    lab_ghost: { es: "Fantasma", en: "Ghost" },
    lab_mask: { es: "Asesino enmascarado", en: "Masked killer" },
    lab_orn: { es: "Ornate", en: "Ornate" },
    lab_min: { es: "Minimal", en: "Minimal" },
    typo_orn: { es: "Ornate", en: "Ornate" },
    typo_dec: { es: "Decorativo", en: "Decorative" },
    typo_std: { es: "Estándar", en: "Standard" },
    typo_clean: { es: "Limpio", en: "Clean" },
    typo_min: { es: "Minimal", en: "Minimal" },
    pk_dark: { es: "pico ~1960", en: "peak ~1960" },
    pk_red: { es: "pico ~2000", en: "peak ~2000" },
    pk_faces: { es: "1945 · 87%", en: "1945 · 87%" },
    pk_shout: { es: "grito ~1955", en: "shout ~1955" },
    pk_blood: { es: "sangre ~2000", en: "blood ~2000" },
    band_reds: { es: "Rojos", en: "Reds" },
    band_dark: { es: "Oscuro", en: "Dark" },
    band_warm: { es: "Cálidos", en: "Warm" },
    band_greens: { es: "Verdes", en: "Greens" },
    band_blues: { es: "Azules", en: "Blues" },
    band_purples: { es: "Púrpuras", en: "Purples" },
    tag_bright: { es: "Más brillante", en: "Brightest" },
    tag_darkest: { es: "Más oscuro", en: "Darkest" },
    tag_red: { es: "Más rojo", en: "Reddest" },
    tag_nored: { es: "Casi sin rojo", en: "Near-zero red" },
    tag_close: { es: "Close-up", en: "Close-up" },
    tag_zero: { es: "Cero rostros", en: "Zero faces" },
    tag_mon: { es: "Monstruo reinante", en: "Reigning monster" },
    tag_orn: { es: "Más ornate", en: "Most ornate" },
    tag_min: { es: "Más minimal", en: "Most minimal" },
    c_fewer: { es: "Mostrar menos", en: "Show fewer" },
  };

  const RIVER = window.RIVER;
  const TYPO = window.TYPO;
  const BLOOD_PIXEL = window.BLOOD_PIXEL;
  const BLOOD_SEMANTIC = window.BLOOD_SEMANTIC;
  const DARK_PTS = window.DARK_PTS;
  const RED_PTS = window.RED_PTS;
  const FACE_PTS = window.FACE_PTS;
  const TEXT_PTS = window.TEXT_PTS;
  const SYM_PTS = window.SYM_PTS;
  const DIAG_PTS = window.DIAG_PTS;
  const CENSUS = window.CENSUS_SERIES;
  const DECADES = window.DECADES;

  if (!RIVER || !DARK_PTS) {
    console.warn("series.js not loaded");
  }

  const ERAS = [
    { year: 1931, title: "THE MONSTER", pal: ["#3b4a2f", "#6b7a3d", "#c9a53f"], tint: "#3b4a2f", img: "images/poster-1920s.png" },
    { year: 1954, title: "ATOMIC BEAST!", pal: ["#f2d13c", "#e07b1f", "#b52a1c"], tint: "#b52a1c", img: "images/poster-1950s.png" },
    { year: 1968, title: "The Dwelling", pal: ["#14141c", "#3d2f4f", "#7d6a3a"], tint: "#3d2f4f", img: "images/poster-1970s.png" },
    { year: 1978, title: "SLAY RIDE", pal: ["#1a0507", "#5c0710", "#c1121f"], tint: "#5c0710", img: "images/poster-1980s.png" },
    { year: 1999, title: "CAPTIVE", pal: ["#12262b", "#2e5158", "#79929a"], tint: "#12262b", img: "images/poster-2000s.png" },
    { year: 2018, title: "the orchard", pal: ["#ece7dd", "#c9beab", "#a33b2e"], tint: "#c9beab", img: "images/poster-2010s.png" },
  ];
  const TEX = ERAS.map((e) => e.img).concat([HALLOWEEN]);
  const TINTS = ERAS.map((e) => e.tint).concat(["#5c0710"]);

  function lerpPts(pts, year) {
    if (!pts || !pts.length) return 0;
    if (year <= pts[0][0]) return pts[0][1];
    if (year >= pts[pts.length - 1][0]) return pts[pts.length - 1][1];
    for (let i = 1; i < pts.length; i++) {
      if (year <= pts[i][0]) {
        const t = (year - pts[i - 1][0]) / (pts[i][0] - pts[i - 1][0]);
        return pts[i - 1][1] + t * (pts[i][1] - pts[i - 1][1]);
      }
    }
    return pts[pts.length - 1][1];
  }
  function decIdx(year) {
    const i = Math.round((Math.floor(year / 10) * 10 - 1920) / 10);
    return Math.max(0, Math.min(10, i));
  }
  function metricsAt(year) {
    const di = decIdx(year);
    return {
      shout: lerpPts(TEXT_PTS, year),
      bright: lerpPts(DARK_PTS, year),
      faces: lerpPts(FACE_PTS, year),
      red: lerpPts(RED_PTS, year),
      dark: RIVER ? RIVER[di][5] : 0,
      blood: BLOOD_SEMANTIC ? BLOOD_SEMANTIC[di] : 0,
      ornate: TYPO ? TYPO[di][0] * 100 : 0,
    };
  }
  ERAS.forEach((e) => {
    e.m = metricsAt(e.year);
  });

  const NEEDLE_MAX = { shout: 40, bright: 55, faces: 100, red: 16, blood: 32, dark: 80, ornate: 80 };
  const NEEDLE_I18N = { shout: "g_shout", bright: "g_bright", faces: "g_faces", red: "g_red", blood: "g_blood", dark: "g_dark", ornate: "g_ornate" };

  const POSES = {
    hero: { cam: [0.12, 0.16, 6.05], look: [-0.08, 0.06, 0], obj: [-0.55, 0.02, 0], rot: [0, 0, 0], scale: 1.04, wall: 1, alpha: 1 },
    intro: { cam: [0.6, 0.5, 5.6], look: [0, 0.1, 0], obj: [0, 0.1, 0], rot: [0, -0.5, 0], scale: 0.88, wall: 0.78, alpha: 0.3 },
    eraL: { cam: [1.5, 0.32, 5.1], look: [0.35, 0.02, 0], obj: [1.38, 0, 0], rot: [0, 0, 0], scale: 1, wall: 0.88, alpha: 1 },
    eraR: { cam: [-1.5, 0.32, 5.1], look: [-0.35, 0.02, 0], obj: [-1.38, 0, 0], rot: [0, 0, 0], scale: 1, wall: 0.88, alpha: 1 },
    specimen: { cam: [0.02, 0.22, 5.2], look: [0, 0.14, 0], obj: [0, 0.28, 0], rot: [0, 0, 0], scale: 1.08, wall: 0.9, alpha: 1 },
    evidence: { cam: [0.2, 0.85, 6.5], look: [0.85, 0.72, 0], obj: [2.55, 1.55, 0.2], rot: [0, -0.2, 0], scale: 0.42, wall: 0.78, alpha: 0 },
    oculto: { cam: [0, 0.55, 6.4], look: [0, 0.1, 0], obj: [0, 0.2, -1.4], rot: [0, 0, 0], scale: 0.5, wall: 0.42, alpha: 0 },
  };

  let lang = "es";
  function initialLang() {
    const q = new URLSearchParams(location.search).get("lang");
    if (q === "es" || q === "en") return q;
    try {
      const saved = localStorage.getItem("aof-lang");
      if (saved === "es" || saved === "en") return saved;
    } catch (e) {}
    return "es";
  }
  function applyLang(next) {
    lang = next;
    document.documentElement.lang = next;
    try {
      localStorage.setItem("aof-lang", next);
    } catch (e) {}
    const u = new URL(location.href);
    u.searchParams.set("lang", next);
    history.replaceState(null, "", u);
    document.querySelectorAll("[data-i]").forEach((el) => {
      const row = I18N[el.getAttribute("data-i")];
      if (!row) return;
      el.textContent = row[next] || row.es;
    });
    document.querySelectorAll("[data-i-html]").forEach((el) => {
      const row = I18N[el.getAttribute("data-i-html")];
      if (!row) return;
      el.innerHTML = row[next] || row.es;
    });
    document.querySelectorAll("[data-lang]").forEach((btn) => {
      btn.setAttribute("aria-pressed", btn.getAttribute("data-lang") === next ? "true" : "false");
    });
    document.title =
      next === "es" ? "Cómo se ve el miedo — Wall cut · Pulp Analytics" : "What Fear Looks Like — Wall cut · Pulp Analytics";
    renderCompare();
    fillAllStrips();
    if (typeof d3 !== "undefined" && RIVER) drawCharts();
  }
  document.querySelectorAll("[data-lang]").forEach((btn) => {
    btn.addEventListener("click", () => applyLang(btn.getAttribute("data-lang")));
  });

  const pre = document.getElementById("preloader");
  const countEl = document.getElementById("count-num");
  let preGone = false;
  function exitPreloader() {
    if (preGone) return;
    preGone = true;
    pre.classList.add("gone");
    pre.style.pointerEvents = "none";
    setTimeout(() => {
      pre.style.display = "none";
    }, 800);
  }
  pre.style.pointerEvents = "none";
  if (REDUCE) exitPreloader();
  else {
    let n = 3;
    countEl.textContent = n;
    const t = setInterval(() => {
      n--;
      if (n <= 0) {
        clearInterval(t);
        exitPreloader();
        return;
      }
      countEl.textContent = n;
    }, 720);
    setTimeout(exitPreloader, 4200);
  }

  const sections = [...document.querySelectorAll(".sec")];
  const railLinks = [...document.querySelectorAll(".year-rail a")];
  let activeTex = 0,
    flipTarget = 0,
    flipAngle = 0,
    assignedFlip = -1;
  let activeNeedle = "shout",
    activeYear = 1931;

  function visWeight(el) {
    if (el && el.id === "specimen") {
      const pin = el.querySelector(".specimen-pin");
      if (pin) el = pin;
    }
    const r = el.getBoundingClientRect();
    const vh = innerHeight;
    const visTop = Math.max(0, r.top);
    const visBot = Math.min(vh, r.bottom);
    const visible = Math.max(0, visBot - visTop);
    if (visible <= 4) return 0;
    const mid = (r.top + r.bottom) / 2;
    const target = vh * 0.42;
    const sigma = vh * 0.38;
    const gauss = Math.exp(-0.5 * ((mid - target) / sigma) ** 2);
    const cover = visible / Math.min(r.height, vh);
    return gauss * Math.max(0.12, cover);
  }
  function damp(a, b, lambda, dt) {
    return a + (b - a) * (1 - Math.exp(-lambda * dt));
  }
  function v3() {
    return { x: 0, y: 0, z: 0 };
  }
  function setV(o, a) {
    o.x = a[0];
    o.y = a[1];
    o.z = a[2];
  }
  function addV(o, a, w) {
    o.x += a[0] * w;
    o.y += a[1] * w;
    o.z += a[2] * w;
  }
  function divV(o, w) {
    o.x /= w;
    o.y /= w;
    o.z /= w;
  }

  function poseFor(name) {
    const src = POSES[name] || POSES.hero;
    const p = {
      cam: src.cam.slice(),
      look: src.look.slice(),
      obj: src.obj.slice(),
      rot: src.rot.slice(),
      scale: src.scale,
      wall: src.wall,
      alpha: src.alpha,
      name,
    };
    if (innerWidth < 768) {
      if (name === "eraL" || name === "eraR") {
        p.cam = [0, 0.4, 5.7];
        p.look = [0, 0.28, 0];
        p.obj = [0, 0.72, 0];
        p.scale = 0.74;
      } else if (name === "hero") {
        p.cam = [0, 0.38, 6.4];
        p.look = [0, 0.12, 0];
        p.obj = [0, 0.85, 0];
        p.scale = 0.58;
      } else if (name === "intro") {
        p.cam = [0, 0.36, 5.9];
        p.look = [0, 0.2, 0];
        p.obj = [0, 0.55, 0];
        p.rot = [0, -0.22, 0];
        p.scale = 0.72;
      } else if (name === "specimen") {
        p.cam = [0, 0.38, 5.7];
        p.look = [0, 0.18, 0];
        p.obj = [0, 0.62, 0];
        p.scale = 0.7;
      } else if (name === "evidence") {
        p.cam = [0, 0.5, 6.5];
        p.look = [0, 0.55, 0];
        p.obj = [1.15, 1.55, 0];
        p.scale = 0.36;
        p.alpha = 0.85;
      }
    }
    return p;
  }

  function blendPoses() {
    const acc = { cam: v3(), look: v3(), obj: v3(), rot: v3(), scale: 0, wall: 0, alpha: 0 };
    let wsum = 0;
    let bestTex = activeTex,
      bestTexW = -1,
      bestNeedle = activeNeedle,
      bestNeedleW = -1,
      bestYear = activeYear,
      bestYearW = -1;
    let bestPose = "hero",
      bestPoseW = -1,
      bestRecapW = -1;
    sections.forEach((sec) => {
      let w = visWeight(sec);
      if (w < 0.008) return;
      w = w * w;
      const p = poseFor(sec.dataset.pose);
      addV(acc.cam, p.cam, w);
      addV(acc.look, p.look, w);
      addV(acc.obj, p.obj, w);
      addV(acc.rot, p.rot, w);
      acc.scale += p.scale * w;
      acc.wall += p.wall * w;
      acc.alpha += p.alpha * w;
      wsum += w;
      if (sec.dataset.tex != null && w > bestTexW) {
        bestTexW = w;
        bestTex = +sec.dataset.tex;
      }
      if (sec.dataset.needle && w > bestNeedleW) {
        bestNeedleW = w;
        bestNeedle = sec.dataset.needle;
      }
      if (sec.dataset.year && w > bestYearW) {
        bestYearW = w;
        bestYear = +sec.dataset.year;
      }
      if (w > bestPoseW) {
        bestPoseW = w;
        bestPose = sec.dataset.pose;
      }
      if (sec.classList.contains("sec-recap") && w > bestRecapW) bestRecapW = w;
    });
    if (wsum < 1e-6) {
      const p = poseFor("hero");
      setV(acc.cam, p.cam);
      setV(acc.look, p.look);
      setV(acc.obj, p.obj);
      setV(acc.rot, p.rot);
      acc.scale = p.scale;
      acc.wall = p.wall;
      acc.alpha = p.alpha;
      bestPose = "hero";
    } else {
      divV(acc.cam, wsum);
      divV(acc.look, wsum);
      divV(acc.obj, wsum);
      divV(acc.rot, wsum);
      acc.scale /= wsum;
      acc.wall /= wsum;
      acc.alpha /= wsum;
    }
    if (bestTexW > 0.02 && bestTex !== activeTex) {
      const dir = bestTex > activeTex ? 1 : -1;
      flipTarget += Math.PI * dir;
      activeTex = bestTex;
    }
    if (bestNeedleW > 0.02) activeNeedle = bestNeedle;
    if (bestYearW > 0.02) activeYear = bestYear;
    acc.hud = bestPose !== "hero" && bestPose !== "oculto" && bestPose !== "specimen";
    acc.pose = bestPose;
    acc.recap = bestRecapW > 0.04;
    return acc;
  }

  const gauge = document.getElementById("gauge");
  const gtx = gauge.getContext("2d");
  let gaugeShown = 18;
  function needleValue() {
    const spec = document.getElementById("specimen");
    if (spec && document.documentElement.dataset.pose === "specimen" && spec.dataset.specVal != null && spec.dataset.specVal !== "") {
      return +spec.dataset.specVal;
    }
    const m = metricsAt(activeYear);
    return m[activeNeedle] ?? m.shout;
  }
  function drawGauge(target) {
    gaugeShown = target;
    const w = gauge.width,
      h = gauge.height,
      cx = w / 2,
      cy = h / 2 + 10,
      r = w * 0.36;
    gtx.clearRect(0, 0, w, h);
    const start = -Math.PI * 0.78,
      end = Math.PI * 0.78;
    gtx.lineWidth = 14;
    gtx.strokeStyle = "rgba(239,230,216,0.12)";
    gtx.beginPath();
    gtx.arc(cx, cy, r, start, end);
    gtx.stroke();
    const max = NEEDLE_MAX[activeNeedle] || 40;
    const t = Math.max(0, Math.min(1, target / max));
    const ang = start + (end - start) * t;
    gtx.strokeStyle = "#a4161a";
    gtx.beginPath();
    gtx.arc(cx, cy, r, start, ang);
    gtx.stroke();
    gtx.strokeStyle = "#efe6d8";
    gtx.lineWidth = 3;
    gtx.beginPath();
    gtx.moveTo(cx, cy);
    gtx.lineTo(cx + Math.cos(ang) * r * 0.82, cy + Math.sin(ang) * r * 0.82);
    gtx.stroke();
    gtx.fillStyle = "#efe6d8";
    gtx.beginPath();
    gtx.arc(cx, cy, 6, 0, Math.PI * 2);
    gtx.fill();
    document.getElementById("gauge-num").textContent = target.toFixed(1);
    const lab = I18N[NEEDLE_I18N[activeNeedle]];
    document.getElementById("gauge-label").textContent = lab ? lab[lang] : "";
  }

  function renderCompare() {
    const a = document.getElementById("pick-a");
    const b = document.getElementById("pick-b");
    if (!a.options.length) {
      ERAS.forEach((e, i) => {
        a.add(new Option(e.year + " · " + e.title, i));
        b.add(new Option(e.year + " · " + e.title, i));
      });
      a.value = "0";
      b.value = "5";
      a.onchange = b.onchange = renderCompare;
    }
    const A = ERAS[+a.value],
      B = ERAS[+b.value];
    const rows = [
      [I18N.cmp_shout[lang], A.m.shout, B.m.shout],
      [I18N.cmp_bright[lang], A.m.bright, B.m.bright],
      [I18N.cmp_faces[lang], A.m.faces, B.m.faces],
      [I18N.cmp_red[lang], A.m.red, B.m.red],
      [I18N.cmp_blood[lang], A.m.blood, B.m.blood],
    ];
    document.getElementById("cmp-rows").innerHTML = rows
      .map((r) => {
        const aw = r[1] > r[2],
          bw = r[2] > r[1];
        return `<div class="cmp-row"><div class="name">${r[0]}</div>
        <div class="val ${aw ? "win" : ""}">${r[1].toFixed(1)}</div>
        <div class="val ${bw ? "win" : ""}">${r[2].toFixed(1)}</div></div>`;
      })
      .join("");
  }

  railLinks.forEach((a, i) => {
    a.addEventListener("keydown", (ev) => {
      if (ev.key === "ArrowDown" || ev.key === "ArrowRight") {
        ev.preventDefault();
        railLinks[Math.min(railLinks.length - 1, i + 1)].focus();
      } else if (ev.key === "ArrowUp" || ev.key === "ArrowLeft") {
        ev.preventDefault();
        railLinks[Math.max(0, i - 1)].focus();
      }
    });
  });

  /* ---------- charts ---------- */
  const BONE = "#efe6d8",
    BLOOD = "#a4161a",
    DIM = "#9a8f82",
    FONT = "DM Mono, ui-monospace, monospace";
  function dressAxis(sel) {
    sel.selectAll("text").attr("fill", BONE).attr("font-family", FONT).attr("font-size", 11);
    sel.selectAll(".domain").attr("stroke", "rgba(239,230,216,.28)");
    sel.selectAll(".tick line").attr("stroke", "rgba(239,230,216,.16)");
  }
  function decYear(i) {
    return 1920 + i * 10;
  }
  function peakOf(pts) {
    return pts.reduce((b, d) => (d[1] > b[1] ? d : b), pts[0]);
  }
  function markPeak(svg, x, y, pt, label, W) {
    if (!pt) return;
    const px = x(pt[0]),
      py = y(pt[1]);
    const right = W && px > W * 0.72;
    svg.append("circle").attr("cx", px).attr("cy", py).attr("r", 4.5).attr("fill", BLOOD).attr("stroke", BONE).attr("stroke-width", 1.5);
    svg
      .append("text")
      .attr("x", right ? px - 10 : px + 10)
      .attr("y", py - 10)
      .attr("text-anchor", right ? "end" : "start")
      .attr("fill", BONE)
      .attr("stroke", "#0a0605")
      .attr("stroke-width", 5)
      .attr("paint-order", "stroke")
      .attr("font-size", 12)
      .attr("font-family", FONT)
      .text(label);
  }
  function lineChart(sel, pts, yMax, color, opts) {
    if (typeof d3 === "undefined" || !pts) return;
    opts = opts || {};
    const svg = d3.select(sel);
    svg.selectAll("*").remove();
    const vb = (svg.attr("viewBox") || "0 0 960 260").split(/\s+/).map(Number);
    const W = vb[2],
      H = vb[3];
    const y0 = opts.yMin || 0;
    const m = opts.spark ? { t: 14, r: 16, b: 28, l: 36 } : { t: 28, r: 32, b: 36, l: 48 };
    const x = d3.scaleLinear().domain(d3.extent(pts, (d) => d[0])).range([m.l, W - m.r]);
    const y = d3.scaleLinear().domain([y0, yMax]).range([H - m.b, m.t]);
    const line = d3.line().x((d) => x(d[0])).y((d) => y(d[1])).curve(d3.curveMonotoneX);
    const area = d3.area().x((d) => x(d[0])).y0(y(y0)).y1((d) => y(d[1])).curve(d3.curveMonotoneX);
    const gid = "ag-" + sel.replace("#", "");
    const lg = svg.append("defs").append("linearGradient").attr("id", gid).attr("x1", "0").attr("y1", "0").attr("x2", "0").attr("y2", "1");
    lg.append("stop").attr("offset", "0%").attr("stop-color", color).attr("stop-opacity", 0.42);
    lg.append("stop").attr("offset", "100%").attr("stop-color", color).attr("stop-opacity", 0.04);
    svg
      .append("g")
      .attr("transform", `translate(${m.l},0)`)
      .call(d3.axisLeft(y).ticks(4).tickSize(-(W - m.l - m.r)).tickFormat(""))
      .call((g) => g.select(".domain").remove())
      .selectAll("line")
      .attr("stroke", "rgba(239,230,216,.12)");
    svg.append("path").attr("d", area(pts)).attr("fill", `url(#${gid})`);
    svg.append("path").attr("d", line(pts)).attr("fill", "none").attr("stroke", color).attr("stroke-width", opts.spark ? 2 : 2.8).attr("stroke-linecap", "round");
    const ax = svg.append("g").attr("transform", `translate(0,${H - m.b})`).call(d3.axisBottom(x).ticks(opts.spark ? 4 : 6).tickFormat(d3.format("d")));
    const ay = svg.append("g").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(4));
    dressAxis(ax);
    dressAxis(ay);
    if (opts.peak) markPeak(svg, x, y, peakOf(pts), I18N[opts.peak][lang], W);
  }
  function twoLineChart(sel, a, b, yMax, ca, cb, peakKey) {
    if (typeof d3 === "undefined") return;
    const svg = d3.select(sel);
    svg.selectAll("*").remove();
    const vb = (svg.attr("viewBox") || "0 0 960 220").split(/\s+/).map(Number);
    const W = vb[2],
      H = vb[3],
      m = { t: 22, r: 28, b: 32, l: 42 };
    const x = d3.scaleLinear().domain(d3.extent(a, (d) => d[0])).range([m.l, W - m.r]);
    const y = d3.scaleLinear().domain([0, yMax]).range([H - m.b, m.t]);
    const line = d3.line().x((d) => x(d[0])).y((d) => y(d[1])).curve(d3.curveMonotoneX);
    const area = d3.area().x((d) => x(d[0])).y0(y(0)).y1((d) => y(d[1])).curve(d3.curveMonotoneX);
    svg.append("path").attr("d", area(b)).attr("fill", cb).attr("opacity", 0.1);
    svg.append("path").attr("d", area(a)).attr("fill", ca).attr("opacity", 0.12);
    svg.append("path").attr("d", line(a)).attr("fill", "none").attr("stroke", ca).attr("stroke-width", 2.4);
    svg.append("path").attr("d", line(b)).attr("fill", "none").attr("stroke", cb).attr("stroke-width", 2.2).attr("stroke-dasharray", "5 4");
    const la = a[a.length - 1],
      lb = b[b.length - 1];
    svg.append("text").attr("x", x(la[0]) - 8).attr("y", y(la[1]) - 8).attr("text-anchor", "end").attr("fill", ca).attr("font-size", 11).attr("font-family", FONT).text(I18N.lab_pixel[lang]);
    svg.append("text").attr("x", x(lb[0]) - 8).attr("y", y(lb[1]) + 16).attr("text-anchor", "end").attr("fill", cb).attr("font-size", 11).attr("font-family", FONT).text(I18N.lab_sem[lang]);
    dressAxis(svg.append("g").attr("transform", `translate(0,${H - m.b})`).call(d3.axisBottom(x).ticks(6).tickFormat(d3.format("d"))));
    dressAxis(svg.append("g").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(4)));
    if (peakKey) markPeak(svg, x, y, peakOf(a), I18N[peakKey][lang], W);
  }
  function riverChart() {
    if (typeof d3 === "undefined" || !RIVER) return;
    const svg = d3.select("#chart-river");
    svg.selectAll("*").remove();
    const W = 960,
      H = 280,
      m = { t: 28, r: 18, b: 36, l: 44 };
    const cols = ["#e02430", "#e5a00d", "#8fb05a", "#5a9eb0", "#b08ad4", "#6a6560"];
    const x = d3.scaleLinear().domain([0, RIVER.length - 1]).range([m.l, W - m.r]);
    const y = d3.scaleLinear().domain([0, 100]).range([H - m.b, m.t]);
    const rows = RIVER.map((r) => ({ k0: r[0], k1: r[1], k2: r[2], k3: r[3], k4: r[4], k5: r[5] }));
    const stack = d3.stack().keys(["k0", "k1", "k2", "k3", "k4", "k5"]);
    const series = stack(rows);
    const area = d3.area().x((d, i) => x(i)).y0((d) => y(d[0])).y1((d) => y(d[1])).curve(d3.curveMonotoneX);
    series.forEach((s, i) => {
      svg.append("path").attr("d", area(s)).attr("fill", cols[i]).attr("opacity", 0.92);
    });
    svg.append("line").attr("x1", x(3)).attr("x2", x(3)).attr("y1", m.t).attr("y2", H - m.b).attr("stroke", BONE).attr("stroke-opacity", 0.45).attr("stroke-dasharray", "3 4");
    svg
      .append("text")
      .attr("x", x(3) + 8)
      .attr("y", m.t + 14)
      .attr("fill", BONE)
      .attr("stroke", "#0a0605")
      .attr("stroke-width", 4)
      .attr("paint-order", "stroke")
      .attr("font-size", 12)
      .attr("font-family", FONT)
      .text(lang === "es" ? "50s cálidos" : "warm '50s");
    dressAxis(
      svg
        .append("g")
        .attr("transform", `translate(0,${H - m.b})`)
        .call(d3.axisBottom(x).tickValues(d3.range(RIVER.length)).tickFormat((i) => String(decYear(i))))
    );
    dressAxis(svg.append("g").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(4).tickFormat((d) => d + "%")));
  }
  function typoChart() {
    if (typeof d3 === "undefined" || !TYPO) return;
    const svg = d3.select("#chart-typo");
    svg.selectAll("*").remove();
    const W = 960,
      H = 260,
      m = { t: 18, r: 16, b: 36, l: 40 };
    const cols = ["#c99a3a", "#b5622f", "#8a6a63", "#6f8792", "#cdc6b6"];
    const x = d3.scaleLinear().domain([0, TYPO.length - 1]).range([m.l, W - m.r]);
    const y = d3.scaleLinear().domain([0, 1]).range([H - m.b, m.t]);
    const rows = TYPO.map((r) => ({ k0: r[0], k1: r[1], k2: r[2], k3: r[3], k4: r[4] }));
    const stack = d3.stack().keys(["k0", "k1", "k2", "k3", "k4"]);
    const series = stack(rows);
    const area = d3.area().x((d, i) => x(i)).y0((d) => y(d[0])).y1((d) => y(d[1])).curve(d3.curveMonotoneX);
    series.forEach((s, i) => {
      svg.append("path").attr("d", area(s)).attr("fill", cols[i]);
    });
    svg.append("text").attr("x", m.l).attr("y", m.t + 2).attr("fill", cols[0]).attr("font-size", 11).attr("font-family", FONT).text(I18N.lab_orn[lang]);
    svg.append("text").attr("x", W - m.r).attr("y", m.t + 2).attr("text-anchor", "end").attr("fill", cols[4]).attr("font-size", 11).attr("font-family", FONT).text(I18N.lab_min[lang]);
    dressAxis(
      svg
        .append("g")
        .attr("transform", `translate(0,${H - m.b})`)
        .call(d3.axisBottom(x).tickValues(d3.range(TYPO.length)).tickFormat((i) => String(decYear(i))))
    );
  }
  function censusChart() {
    if (typeof d3 === "undefined" || !CENSUS) return;
    const svg = d3.select("#chart-census");
    svg.selectAll("*").remove();
    const W = 960,
      H = 240,
      m = { t: 22, r: 18, b: 32, l: 40 };
    const keys = Object.keys(CENSUS);
    const all = keys.flatMap((k) => CENSUS[k]);
    const x = d3.scaleLinear().domain([1920, 2020]).range([m.l, W - m.r]);
    const y = d3.scaleLinear().domain([0, d3.max(all, (d) => d[1]) || 10]).range([H - m.b, m.t]);
    const line = d3.line().x((d) => x(d[0])).y((d) => y(d[1])).curve(d3.curveMonotoneX);
    keys.forEach((k) => {
      const hi = k === "ghost" || k === "masked killer";
      const pts = CENSUS[k].filter((p) => p[0] >= 1920);
      svg
        .append("path")
        .attr("d", line(pts))
        .attr("fill", "none")
        .attr("stroke", hi ? (k === "ghost" ? BONE : BLOOD) : "rgba(239,230,216,.16)")
        .attr("stroke-width", hi ? 2.4 : 1);
      if (hi && pts.length) {
        const last = pts[pts.length - 1];
        svg
          .append("text")
          .attr("x", x(last[0]) - 4)
          .attr("y", y(last[1]) - 8)
          .attr("text-anchor", "end")
          .attr("fill", k === "ghost" ? BONE : BLOOD)
          .attr("font-size", 11)
          .attr("font-family", FONT)
          .text(k === "ghost" ? I18N.lab_ghost[lang] : I18N.lab_mask[lang]);
      }
    });
    dressAxis(svg.append("g").attr("transform", `translate(0,${H - m.b})`).call(d3.axisBottom(x).ticks(6).tickFormat(d3.format("d"))));
  }

  const SIX = ["1920s–30s", "1940s–50s", "1960s–70s", "1980s", "1990s–2000s", "2010s"];
  const STRIPS = {
    color: [
      { tag: "band_reds", color: "#e02430", soft: false, items: [[45803, "Svengali", "1931"], [329237, "Gigantis: The Fire Monster", "1959"], [49183, "The Vengeance of Fu Manchu", "1967"], [10676, "Halloween III", "1982"], [170, "28 Days Later", "2002"], [882598, "Smile", "2022"]] },
      { tag: "band_dark", color: "#9a958a", soft: false, items: [[150196, "The Telltale Heart", "1928"], [11868, "Dracula", "1958"], [348, "Alien", "1979"], [4488, "Friday the 13th", "1980"], [565, "The Ring", "2002"], [310131, "The Witch", "2015"]] },
      { tag: "band_warm", color: "#e5a00d", soft: true, items: [[136, "Freaks", "1932"], [11549, "Invasion of the Body Snatchers", "1956"], [59189, "Phase IV", "1974"], [694, "The Shining", "1980"], [1946, "eXistenZ", "1999"], [425972, "Cargo", "2017"]] },
      { tag: "band_greens", color: "#8fb05a", soft: true, items: [[28046, "The Ghoul", "1933"], [10973, "Creature from the Black Lagoon", "1954"], [805, "Rosemary's Baby", "1968"], [18498, "Ghoulies", "1985"], [38299, "The Human Centipede", "2009"], [591275, "Fear Street: 1666", "2021"]] },
      { tag: "band_blues", color: "#5a9eb0", soft: true, items: [[84712, "The Last Warning", "1928"], [35911, "Cult of the Cobra", "1955"], [578, "Jaws", "1975"], [1091, "The Thing", "1982"], [4970, "Gothika", "2003"], [332567, "The Shallows", "2016"]] },
      { tag: "band_purples", color: "#b08ad4", soft: true, items: [[1266263, "Black Ghost", "1937"], [831, "This Island Earth", "1955"], [15360, "The Night Stalker", "1972"], [28774, "Communion", "1989"], [70772, "Don't Look Under the Bed", "1999"], [419479, "The Babysitter", "2017"]] },
    ],
    dark: [
      { tag: "tag_bright", color: "#f0e6c0", items: [[147087, "The Cobweb Hotel", "1936"], [11815, "The Fly", "1958"], [571, "The Birds", "1963"], [45878, "Return to Horror High", "1987"], [883891, "The Making of Saw", "2004"], [416753, "Neal", "2011"]] },
      { tag: "tag_darkest", color: "#1c1a17", items: [[31592, "The Old Dark House", "1932"], [11868, "Dracula", "1958"], [11586, "Exorcist II: The Heretic", "1977"], [9980, "Maximum Overdrive", "1986"], [4283, "Primeval", "2007"], [751423, "Don't Let It In", "2020"]] },
    ],
    blood: [
      { tag: "tag_red", color: "#a4161a", items: [[45803, "Svengali", "1931"], [117429, "Jack the Ripper", "1959"], [28532, "Castle of Blood", "1964"], [10493, "Dead Calm", "1989"], [127642, "Feng Shui", "2004"], [564446, "Hell Bound", "2018"]] },
      { tag: "tag_nored", color: "#4c5a66", items: [[39259, "Dracula", "1931"], [3076, "Frankenstein Meets the Wolf Man", "1943"], [93929, "The Haunted House of Horror", "1969"], [1091, "The Thing", "1982"], [24198, "AVH: Alien vs. Hunter", "2007"], [575869, "The Yellow Night", "2019"]] },
    ],
    faces: [
      { tag: "tag_close", color: "#e5a00d", items: [[653, "Nosferatu", "1922"], [363059, "The Fall of the House of Usher", "1942"], [29748, "Taste the Blood of Dracula", "1970"], [29077, "The Bride", "1985"], [60086, "Babysitter Wanted", "2007"], [476299, "Ghostland", "2018"]] },
      { tag: "tag_zero", color: "#6b6258", items: [[58129, "The Phantom Carriage", "1921"], [1678, "Godzilla", "1954"], [348, "Alien", "1979"], [1091, "The Thing", "1982"], [73336, "Buried Alive II", "1997"], [345940, "The Meg", "2018"]] },
    ],
    type: [
      { tag: "tag_orn", color: "#c99a3a", items: [[15849, "The Mummy", "1932"], [85498, "The Maze", "1953"], [23439, "House of Usher", "1960"], [16281, "Creepshow", "1982"], [439917, "Devil Medusa", "1995"], [535412, "Arte Factum", "2017"]] },
      { tag: "tag_min", color: "#cdc6b6", items: [[84713, "The Last Performance", "1929"], [495447, "Whistle and I'll Come to You", "1956"], [39995, "Long Weekend", "1979"], [46767, "In a Glass Cage", "1987"], [16028, "They", "2002"], [875138, "Alone", "2021"]] },
    ],
  };

  function fillStrip(id, rows, withHead) {
    const box = document.getElementById(id);
    if (!box) return;
    const more = box.querySelector(".strip-more");
    const moreHTML = more ? more.outerHTML : "";
    const wasOpen = box.classList.contains("is-open");
    const head = withHead
      ? `<div class="strip-row">${["", ...SIX].map((s, i) => (i === 0 ? `<div></div>` : `<div class="strip-head">${s}</div>`)).join("")}</div>`
      : "";
    const html = rows
      .map((row) => {
        const cards = row.items
          .map(([tid, title, year]) => {
            const src = posterSrc(tid);
            return `<a class="strip-card" href="https://www.themoviedb.org/movie/${tid}" target="_blank" rel="noopener"><img src="${src}" alt="${title} (${year})" loading="lazy" onerror="this.style.opacity=.2"><span><b>${title}</b><br>${year}</span></a>`;
          })
          .join("");
        const lab = I18N[row.tag] ? I18N[row.tag][lang] : row.tag;
        return `<div class="strip-row${row.soft ? " strip-soft" : ""}"><div class="strip-tag"><span class="strip-dot" style="background:${row.color}"></span>${lab}</div>${cards}</div>`;
      })
      .join("");
    box.innerHTML = moreHTML + head + html;
    if (wasOpen) box.classList.add("is-open");
    const btn = box.querySelector(".strip-more");
    if (btn) {
      btn.textContent = (wasOpen ? I18N.c_fewer : I18N.c_more)[lang];
      btn.setAttribute("aria-expanded", wasOpen ? "true" : "false");
    }
  }

  function fillAllStrips() {
    if (!STRIPS) return;
    fillStrip("strip-color", STRIPS.color, true);
    fillStrip("strip-dark", STRIPS.dark, true);
    fillStrip("strip-blood", STRIPS.blood, true);
    fillStrip("strip-faces", STRIPS.faces, true);
    fillStrip("strip-type", STRIPS.type, true);
  }

  function drawCharts() {
    riverChart();
    lineChart("#chart-dark", DARK_PTS, 52, BONE, { yMin: 24, peak: "pk_dark" });
    const decYears = (DECADES || []).map((d, i) => 1920 + i * 10);
    const pix = decYears.map((y, i) => [y, BLOOD_PIXEL[i]]);
    const sem = decYears.map((y, i) => [y, BLOOD_SEMANTIC[i]]);
    twoLineChart("#chart-blood", pix, sem, 30, BLOOD, BONE, "pk_red");
    lineChart("#chart-faces", FACE_PTS, 100, BONE, { peak: "pk_faces" });
    censusChart();
    lineChart("#chart-quiet", TEXT_PTS, 40, BLOOD, { peak: "pk_shout" });
    lineChart("#chart-sym", SYM_PTS, 1, BONE, { spark: true, yMin: 0.7 });
    lineChart("#chart-diag", DIAG_PTS, 40, BLOOD, { spark: true, yMin: 20 });
    typoChart();
  }

  document.getElementById("strip-color")?.addEventListener("click", (e) => {
    const btn = e.target.closest("#color-more");
    if (!btn) return;
    const strip = document.getElementById("strip-color");
    const on = strip.classList.toggle("is-open");
    btn.setAttribute("aria-expanded", on ? "true" : "false");
    btn.textContent = (on ? I18N.c_fewer : I18N.c_more)[lang];
  });

  /* ---------- 3D ---------- */
  const wallBg = document.getElementById("wall-bg");
  const tint = document.getElementById("tint");
  const hud = document.getElementById("hud-gauge");
  const img2d = document.getElementById("poster2d-img");
  const mouse = { tx: 0, ty: 0, x: 0, y: 0 };
  addEventListener("pointermove", (e) => {
    mouse.tx = e.clientX / innerWidth - 0.5;
    mouse.ty = e.clientY / innerHeight - 0.5;
  });

  const cur = {
    cam: { x: 0, y: 0.62, z: 6.15 },
    look: { x: 0, y: 0.42, z: 0 },
    obj: { x: 0, y: 0.95, z: 0 },
    rot: { x: 0, y: 0, z: 0 },
    scale: 0.78,
    wall: 1,
    alpha: 1,
    tint: [59 / 255, 74 / 255, 47 / 255],
  };

  function canWebGL() {
    return typeof THREE !== "undefined" && typeof WebGLRenderingContext !== "undefined";
  }

  let renderer, scene, camera, card, frontMat, backMat, wrapper, textures = [];
  let use3d = canWebGL();

  function hexToRgb(h) {
    const n = parseInt(h.slice(1), 16);
    return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
  }
  function texSrc(i) {
    return TEX[i] || TEX[0];
  }
  function assignIncomingTexture() {
    const showBack = ((Math.round(flipTarget / Math.PI) % 2) + 2) % 2;
    const tex = textures[activeTex];
    if (!tex || !frontMat) return;
    if (showBack) {
      backMat.map = tex;
      backMat.needsUpdate = true;
    } else {
      frontMat.map = tex;
      frontMat.needsUpdate = true;
    }
    assignedFlip = showBack;
    img2d.src = texSrc(activeTex);
  }

  function makeCard() {
    const W = 1.02,
      H = 1.53,
      T = 0.032;
    const group = new THREE.Group();
    const geo = new THREE.PlaneGeometry(W, H);
    const matOpts = {
      map: textures[0],
      color: 0xffffff,
      transparent: true,
      opacity: 1,
      polygonOffset: true,
      polygonOffsetFactor: -2,
      polygonOffsetUnits: -2,
    };
    frontMat = new THREE.MeshBasicMaterial(matOpts);
    backMat = new THREE.MeshBasicMaterial(Object.assign({}, matOpts));
    const front = new THREE.Mesh(geo, frontMat);
    const back = new THREE.Mesh(geo, backMat);
    back.rotation.y = Math.PI;
    front.position.z = T / 2 + 0.0015;
    back.position.z = -(T / 2 + 0.0015);
    const edge = new THREE.Mesh(new THREE.BoxGeometry(W - 0.02, H - 0.02, T), new THREE.MeshBasicMaterial({ color: 0x1a1008 }));
    const frameMat = new THREE.MeshBasicMaterial({ color: 0x6b4a28 });
    const ft = 0.055,
      fd = 0.046;
    const mk = (w, h, x, y) => {
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, fd), frameMat);
      mesh.position.set(x, y, 0);
      return mesh;
    };
    group.add(edge, front, back, mk(W + ft * 2, ft, 0, H / 2 + ft / 2), mk(W + ft * 2, ft, 0, -H / 2 - ft / 2), mk(ft, H, -W / 2 - ft / 2, 0), mk(ft, H, W / 2 + ft / 2, 0));
    return group;
  }

  const CARD_ART_W = 1.02,
    CARD_ART_H = 1.53,
    CARD_FRAME = 0.055;
  const _proj = typeof THREE !== "undefined" ? new THREE.Vector3() : null;
  const stageEl = document.getElementById("specimen-stage");

  function projectCardRect() {
    if (!camera || !card || !_proj) return null;
    card.updateWorldMatrix(true, false);
    const corners = [
      [-CARD_ART_W / 2, CARD_ART_H / 2, 0.02],
      [CARD_ART_W / 2, CARD_ART_H / 2, 0.02],
      [CARD_ART_W / 2, -CARD_ART_H / 2, 0.02],
      [-CARD_ART_W / 2, -CARD_ART_H / 2, 0.02],
    ];
    let minX = 1e9,
      minY = 1e9,
      maxX = -1e9,
      maxY = -1e9;
    for (let i = 0; i < 4; i++) {
      _proj.set(corners[i][0], corners[i][1], corners[i][2]);
      card.localToWorld(_proj);
      _proj.project(camera);
      const sx = (_proj.x * 0.5 + 0.5) * innerWidth;
      const sy = (-_proj.y * 0.5 + 0.5) * innerHeight;
      if (sx < minX) minX = sx;
      if (sy < minY) minY = sy;
      if (sx > maxX) maxX = sx;
      if (sy > maxY) maxY = sy;
    }
    return { left: minX, top: minY, width: maxX - minX, height: maxY - minY };
  }

  function pinSpecimenStage() {
    if (!stageEl || REDUCE) return;
    const pin = document.querySelector(".specimen-pin");
    const on = pin && visWeight(pin) > 0.03;
    stageEl.style.visibility = on ? "visible" : "hidden";
    stageEl.style.opacity = on ? "1" : "0";
    if (!on) return;
    let rect = null;
    if (use3d && camera && card) rect = projectCardRect();
    if (!rect) {
      const img = document.getElementById("poster2d-img");
      if (img && img.getClientRects().length) {
        const r = img.getBoundingClientRect();
        const pad = 10;
        rect = { left: r.left + pad, top: r.top + pad, width: r.width - pad * 2, height: r.height - pad * 2 };
      }
    }
    if (!rect || rect.width < 24 || rect.height < 24) return;
    stageEl.style.left = rect.left + "px";
    stageEl.style.top = rect.top + "px";
    stageEl.style.width = rect.width + "px";
    stageEl.style.height = rect.height + "px";
    stageEl.style.transform = "none";
    stageEl.style.setProperty("--frame", (rect.height * CARD_FRAME) / CARD_ART_H + "px");
  }

  function init3d() {
    const canvas = document.getElementById("scene");
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setClearColor(0x000000, 0);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(32, innerWidth / innerHeight, 0.1, 40);
    camera.position.set(0, 0.62, 6.15);
    wrapper = new THREE.Group();
    card = makeCard();
    wrapper.add(card);
    scene.add(wrapper);
    resize();
  }

  function resize() {
    if (!renderer) return;
    renderer.setSize(innerWidth, innerHeight, false);
    camera.aspect = innerWidth / innerHeight;
    camera.updateProjectionMatrix();
  }
  addEventListener("resize", resize);

  function loadTextures(done) {
    const loader = new THREE.TextureLoader();
    loader.crossOrigin = "anonymous";
    let left = TEX.length;
    textures = TEX.map((src) => {
      const tex = loader.load(
        src,
        (t) => {
          t.colorSpace = THREE.SRGBColorSpace;
          t.minFilter = THREE.LinearFilter;
          if (renderer) t.anisotropy = renderer.capabilities.getMaxAnisotropy();
          if (--left <= 0 && done) done();
        },
        undefined,
        () => {
          if (--left <= 0 && done) done();
        }
      );
      tex.colorSpace = THREE.SRGBColorSpace;
      tex.minFilter = THREE.LinearFilter;
      return tex;
    });
  }

  function apply2dPose(p) {
    const mobile = innerWidth < 768;
    let left = "50%",
      top = "10vh";
    if (p.name === "eraL" && !mobile) {
      left = "72%";
      top = "14vh";
    }
    if (p.name === "eraR" && !mobile) {
      left = "28%";
      top = "14vh";
    }
    if (mobile && (p.name === "eraL" || p.name === "eraR" || p.name === "intro")) {
      top = "8vh";
      left = "50%";
    }
    if (p.name === "hero") {
      top = mobile ? "8vh" : "16vh";
      left = mobile ? "50%" : "38%";
    }
    if (p.name === "specimen") {
      top = mobile ? "8vh" : "10vh";
      left = "50%";
    }
    if (p.name === "evidence") {
      left = mobile ? "82%" : "90%";
      top = mobile ? "6vh" : "6vh";
    }
    img2d.style.left = left;
    img2d.style.top = top;
    img2d.style.opacity = String(p.alpha);
    if (p.name === "evidence") {
      img2d.style.height = mobile ? "22vh" : "26vh";
    } else {
      img2d.style.height = "";
    }
    img2d.src = texSrc(activeTex);
  }
  img2d.src = TEX[0];

  const lambdaCam = REDUCE ? 16 : 4.1;
  const lambdaFlip = REDUCE ? 14 : 5.2;
  let last = performance.now();

  const specimenFilm = (function initSpecimenFilm() {
    const sec = document.getElementById("specimen");
    const film = document.getElementById("specimen-film");
    const dots = document.getElementById("specimen-dots");
    if (!sec || !film || !dots) return { tick() {} };
    const cards = [...film.querySelectorAll(".spec-card")];
    const overlays = [...sec.querySelectorAll(".spec-ov")];
    dots.innerHTML = cards
      .map((_, i) => `<button type="button" data-beat="${i}" aria-label="${i + 1}"></button>`)
      .join("");
    const btns = [...dots.querySelectorAll("button")];
    const gap = 14;

    function progress() {
      if (REDUCE) return 0;
      const r = sec.getBoundingClientRect();
      const range = Math.max(1, r.height - innerHeight);
      return Math.max(0, Math.min(1, -r.top / range));
    }

    function apply(p) {
      const n = Math.max(1, cards.length - 1);
      const i = Math.min(cards.length - 1, Math.round(p * n));
      if (!REDUCE && cards[0]) {
        const step = cards[0].getBoundingClientRect().width + gap;
        film.style.transform = `translate3d(${-(p * n * step)}px,0,0)`;
      }
      cards.forEach((c, k) => c.classList.toggle("is-on", k === i));
      btns.forEach((b, k) => {
        if (k === i) b.setAttribute("aria-current", "true");
        else b.removeAttribute("aria-current");
      });
      overlays.forEach((ov) => ov.classList.toggle("on", +ov.dataset.beat === i));
      const card = cards[i];
      if (card) {
        sec.dataset.needle = card.dataset.needle;
        sec.dataset.specVal = card.dataset.val;
      }
    }

    btns.forEach((b) => {
      b.addEventListener("click", () => {
        const i = +b.dataset.beat;
        const range = Math.max(1, sec.offsetHeight - innerHeight);
        const n = Math.max(1, cards.length - 1);
        const top = sec.getBoundingClientRect().top + scrollY + (i / n) * range;
        scrollTo({ top, behavior: REDUCE ? "auto" : "smooth" });
      });
    });

    apply(0);
    return {
      tick() {
        apply(progress());
      },
    };
  })();

  function tick(now) {
    specimenFilm.tick();
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    const blended = blendPoses();
    const k = lambdaCam;
    cur.cam.x = damp(cur.cam.x, blended.cam.x, k, dt);
    cur.cam.y = damp(cur.cam.y, blended.cam.y, k, dt);
    cur.cam.z = damp(cur.cam.z, blended.cam.z, k, dt);
    cur.look.x = damp(cur.look.x, blended.look.x, k, dt);
    cur.look.y = damp(cur.look.y, blended.look.y, k, dt);
    cur.look.z = damp(cur.look.z, blended.look.z, k, dt);
    cur.obj.x = damp(cur.obj.x, blended.obj.x, k, dt);
    cur.obj.y = damp(cur.obj.y, blended.obj.y, k, dt);
    cur.obj.z = damp(cur.obj.z, blended.obj.z, k, dt);
    cur.rot.x = damp(cur.rot.x, blended.rot.x, k, dt);
    cur.rot.y = damp(cur.rot.y, blended.rot.y, k, dt);
    cur.scale = damp(cur.scale, blended.scale, k, dt);
    cur.wall = damp(cur.wall, blended.wall, k * 0.8, dt);
    cur.alpha = damp(cur.alpha, blended.alpha, k, dt);
    flipAngle = damp(flipAngle, flipTarget, lambdaFlip, dt);

    const rgb = hexToRgb(TINTS[activeTex] || ERAS[0].tint);
    cur.tint[0] = damp(cur.tint[0], rgb[0], 3.2, dt);
    cur.tint[1] = damp(cur.tint[1], rgb[1], 3.2, dt);
    cur.tint[2] = damp(cur.tint[2], rgb[2], 3.2, dt);
    tint.style.background = `rgb(${(cur.tint[0] * 255) | 0},${(cur.tint[1] * 255) | 0},${(cur.tint[2] * 255) | 0})`;
    if (wallBg) wallBg.style.opacity = cur.wall.toFixed(3);
    hud.classList.toggle("is-on", blended.hud);
    document.documentElement.dataset.pose = blended.pose || "";
    document.querySelector(".year-rail")?.classList.toggle("is-eras", !!blended.recap);

    mouse.x = damp(mouse.x, mouse.tx, REDUCE ? 20 : 3.4, dt);
    mouse.y = damp(mouse.y, mouse.ty, REDUCE ? 20 : 3.4, dt);

    const showBack = ((Math.round(flipTarget / Math.PI) % 2) + 2) % 2;
    if (showBack !== assignedFlip) assignIncomingTexture();

    function railWeight(a) {
      const href = a.getAttribute("href");
      const el = document.querySelector(href);
      let w = el ? visWeight(el) : 0;
      if (href && href.startsWith("#act-")) {
        const ev = document.querySelector("#ev-" + href.slice(5));
        if (ev) w = Math.max(w, visWeight(ev));
      }
      return w;
    }
    let bestA = null,
      bestW = -1;
    railLinks.forEach((a) => {
      const w = railWeight(a);
      if (w > bestW) {
        bestW = w;
        bestA = a;
      }
    });
    if (bestW < 0.08 || !blended.hud) bestA = null;
    railLinks.forEach((a) => a.setAttribute("aria-current", a === bestA ? "true" : "false"));

    const gTarget = needleValue();
    gaugeShown = damp(gaugeShown, gTarget, REDUCE ? 18 : 5, dt);
    drawGauge(gaugeShown);

    if (use3d && renderer) {
      camera.position.set(cur.cam.x, cur.cam.y, cur.cam.z);
      camera.lookAt(cur.look.x, cur.look.y, cur.look.z);
      wrapper.position.set(cur.obj.x + mouse.x * 0.22, cur.obj.y, cur.obj.z + mouse.y * 0.18);
      wrapper.rotation.set(cur.rot.x, cur.rot.y, 0);
      wrapper.scale.setScalar(cur.scale);
      card.rotation.y = flipAngle;
      if (frontMat) {
        frontMat.opacity = cur.alpha;
        backMat.opacity = cur.alpha;
        const ghost = cur.alpha < 0.99;
        frontMat.transparent = ghost;
        backMat.transparent = ghost;
        frontMat.depthWrite = !ghost;
        backMat.depthWrite = !ghost;
        wrapper.visible = cur.alpha > 0.02;
      }
    renderer.render(scene, camera);
    pinSpecimenStage();
    } else {
      const best = sections.reduce(
        (acc, sec) => {
          const w = visWeight(sec);
          return w > (acc.w || 0) ? { w, name: sec.dataset.pose } : acc;
        },
        { w: 0, name: "hero" }
      );
      apply2dPose({ name: best.name, alpha: cur.alpha, scale: cur.scale });
      pinSpecimenStage();
    }
    requestAnimationFrame(tick);
  }

  applyLang(initialLang());
  renderCompare();
  if (RIVER) drawCharts();
  drawGauge(metricsAt(1931).shout);

  if (use3d) {
    try {
      loadTextures(() => {});
      init3d();
    } catch (err) {
      use3d = false;
      document.body.classList.add("no-webgl");
    }
  } else {
    document.body.classList.add("no-webgl");
  }
  requestAnimationFrame(tick);
})();
