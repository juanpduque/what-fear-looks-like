import { pct, num } from './format.js';

export { pct, num };

const IMG_S = 'https://image.tmdb.org/t/p/w92';
const IMG_L = 'https://image.tmdb.org/t/p/w780';
const IMG_M = 'https://image.tmdb.org/t/p/w500';

export const HAS_DATA = typeof window.POSTERS !== 'undefined';

export function creatureLabels() {
  const t = window.t;
  return {
    giant_monster: t('creature_giant_monster'),
    masked_killer: t('creature_masked_killer'),
    wolf_dog: t('creature_wolf_dog'),
    animal: t('creature_animal'),
  };
}

export const POSTER_BY_ID = HAS_DATA
  ? Object.fromEntries(window.POSTERS.map((p) => [p[7], p]))
  : {};

export const SPECIMEN_PATHS={170:"/sQckQRt17VaWbo39GIu0TMOiszq.jpg",348:"/vfrQk5IPloGg1v9Rzbh2Eg3VGyM.jpg",377:"/wGTpGGRMZmyFCcrY2YoxVTIBlli.jpg",565:"/e2t5CKMox7tjv3iD3Ko7NdFa5lJ.jpg",571:"/z0iYrJ6GsAMP3abOha7uGMuc5kZ.jpg",578:"/lxM6kqilAdpdhqUl2biYp5frUxE.jpg",694:"/nRj5511mZdTl4saWEPoj9QroTIu.jpg",805:"/s8pdaHjxNPLXIA1WjSTWm00RJTz.jpg",831:"/2viRDpHmhzQoreZok2auLjkVbSE.jpg",948:"/qVpCaBcnjRzGL3nOPHi6Suy0sB6.jpg",1091:"/tzGY49kseSE9QAKk47uuDGwnSCu.jpg",1678:"/ixfHV61iRM4Jkgw0uI5ICtNwfmX.jpg",1946:"/kETKF0JhdTPn1knci8CAdYL0d79.jpg",3053:"/iH8Ohx97F2eIagrJGzCEraO93MN.jpg",4283:"/5ou56J8FIxbIFusR9zIA9GW7zwt.jpg",4488:"/HzrPn1gEHWixfMOvOehOTlHROo.jpg",4970:"/frSGNQcWx1ek8dCduFYCux1ho7n.jpg",9841:"/1qAQWKjfAgxQN4atIMWnssBWHOf.jpg",9980:"/cFrKCumtZMHCWwWNxgGRyaxhYu2.jpg",10065:"/4D246dpe7yy2GvHI2IbpeqkUXry.jpg",10493:"/hXpav86ZX5N1YIfVfVtzuZLNrjW.jpg",10676:"/4qDtn4RNIEY4OgitIxi3P1CtthO.jpg",10973:"/aGM3tYt0r2NO4Uc8dNEbAMhXeEk.jpg",11470:"/jrObEGWVW1XlutjYXqyyGxtTeov.jpg",11549:"/wVXt7h98sTKhLjq1TdvdGwdyJo8.jpg",11586:"/g9i3LTMYLRHvCYSKimZEfd1Vqy7.jpg",11815:"/kXdBcDh2EbgSIf4Oo1dxKapZM2f.jpg",11868:"/1L45hwUu1P4NRhbRRrE5d9oHamm.jpg",15360:"/dij60cVBL39B5t1SdGQr33APksC.jpg",16028:"/nHG0VOW6o99tP5EACtKTMADqxJQ.jpg",16281:"/4SoyTCEpsgLjX6yAyMsx3AsAyRQ.jpg",18498:"/yV8z6deULhH4oJAUj2YdhITPwfc.jpg",18983:"/19RDmhX6LtzMxv0KXXAU1IBIvvA.jpg",21588:"/cI5AV3jCuxmoQp0N7Z16SI2b7Xk.jpg",23439:"/jEzZOrGSWpl0jKOIXoY3OnEabLQ.jpg",24198:"/46whh6JCDqRFxHfKssePScUvD8D.jpg",28532:"/A17gEQk617FsLhtPyalRN885KM3.jpg",28659:"/uecOR4c3IrZ2AusokpyifrtJks9.jpg",28774:"/5WsMyE6wwY2QbM3fpAePOX3e7pZ.jpg",29077:"/a5cCwJEnVSPtTqHgIE9UxHIoWFl.jpg",29748:"/3xMrdNnyvYrdJaKq9dWJKkTHGvP.jpg",31682:"/1Tl2aeOhvUmEHSGHGH5SfmN19vQ.jpg",35911:"/ypQ7rC8lUgt9g7yAMmmfq5vx0Fo.jpg",38299:"/2tP5jkSJ8Nu3OsIQLaCEktepOLp.jpg",39995:"/p9S9UuYA4uHdoH9FecB3sU9zpfm.jpg",43115:"/4uns8WSxu9LSFv0FkJP8uv6Q5kQ.jpg",45878:"/glZ0Wz5u2Vr7TzM6Kj1f4e6EliU.jpg",46767:"/64rlKmchkFyLDh6XP2XqPHw9nPd.jpg",48885:"/eHzJBkfEV4fUVxAfspt1jOxBIc.jpg",49183:"/njSWFPeTaZYoKKeuyf1Ga6OYAuh.jpg",50606:"/mPH3YLnyU5qT7FUMd1U1wWD41Ep.jpg",52199:"/yZHinX5xzbkhXvX5t4lxKuDQEHQ.jpg",54653:"/bjVqT8XIVMTCWpSreMpH0W6Rjxi.jpg",59189:"/zeM6HitVufjH9nvWvg4MraucwzU.jpg",60086:"/7DQlbb4ax5L5NZvMjr54KOsXGyF.jpg",70772:"/zVK76DDtIKdIiRRraAVrsyek04t.jpg",72153:"/bLYZAd3yukk9HFamT16XHFrmKtw.jpg",73336:"/ztg12ZJK2Vi8tHl9vsNxFJ1hc4A.jpg",74915:"/2CafSu1hxvxLRYTiFuhA3sH0xNP.jpg",85498:"/xlfJKdjwUZNfT2QUEUv0RozVuEs.jpg",88353:"/f7IxkjIQWDiVgrUmkfA3HYljuJF.jpg",93929:"/vjpqjUYOS9Nv2nEkNuo2UoNdtPv.jpg",117429:"/fQ4xCUh2sL3B5EqTXoLHn9uAnGN.jpg",127642:"/4tSMIUeLYGQFeBnHgS7TVuYiAi0.jpg",141442:"/2oBgGXtsh2GvnBesUAqlHvf5Q7P.jpg",145850:"/2nPPxIb8Rlbwvs4HsjOmZsa2QlE.jpg",156068:"/qObcGnlli4zlCc99DpTQv95GBZy.jpg",212005:"/dRKpOGEJLLnD0QYFn8ku4DBYwGz.jpg",226630:"/y3j0wddj5U6W9ZBL8NxPQOxLgJo.jpg",279690:"/vzqwe4uuINJhbPqvlbVShBnCvHv.jpg",310131:"/zap5hpFCWSvdWSuPGAQyjUv2wAC.jpg",329237:"/6YcIEhXzMSuNdrooBUsO3mZK8rT.jpg",332567:"/42HlPJmiE6rQdtT2lYzPPMQYvqG.jpg",345940:"/xqECHNvzbDL5I3iiOVUkVPJMSbc.jpg",416753:"/gVBUEYI8eIaFZZv5BR6DPVuJZsS.jpg",419479:"/86a7GRVRCwfl7wdI4QadyvKa6Zu.jpg",425972:"/cdPSUck4tBRvRu6DFk6XciDrssn.jpg",439917:"/soP8q3FtbTseRVcJavkXDuhVFac.jpg",460458:"/7uRbWOXxpWDMtnsd2PF3clu65jc.jpg",476299:"/tt9YSQlArAj6849SQQJ5ryNgcJs.jpg",495447:"/stTZqv11cqWOZbTySSpf6ciDnr2.jpg",519418:"/pNrdzyE39G6brgCF1YmrW73aecy.jpg",535412:"/sPEh50GkEO3mTMdwn3Dz1LjEp9h.jpg",564446:"/1c9os1zQi5X0hey7J9PKGBGFYHm.jpg",575869:"/gkDW017O3DLK9vBMEcAMSunnuo9.jpg",591275:"/rmEPtz3Ufzol2VWUAZYzOFaBio3.jpg",751423:"/gTOl98Sqie5pDxomspvWLXN66BJ.jpg",875138:"/6MPBRoFpEWpohhKZqT19q62U8If.jpg",882598:"/hiaeZKzwsk4y4atFhmncO5KRxeT.jpg",883891:"/gpXdkzoens2K8VtVaMORem9f95.jpg"}

export function tmdbImg(path, size) {
  if (!path) return '';
  const raw = String(path);
  if (raw.startsWith('http://') || raw.startsWith('https://')) return raw;
  const base = size === 's' ? IMG_S : size === 'l' ? IMG_L : IMG_M;
  return raw.startsWith('/') ? base + raw : `${base}/${raw}`;
}

export function posterSrc(p, size) {
  const base = size === 's' ? IMG_S : size === 'm' ? IMG_M : IMG_L;
  if (p && p[2]) return base + p[2];
  return posterSrcById(p[7], size);
}

export function posterSrcById(id, size) {
  const base = size === 's' ? IMG_S : size === 'l' ? IMG_L : IMG_M;
  const row = POSTER_BY_ID[id];
  if (row && row[2]) return base + row[2];
  if (SPECIMEN_PATHS[id]) return base + SPECIMEN_PATHS[id];
  return `assets/posters/${id}.jpg`;
}
