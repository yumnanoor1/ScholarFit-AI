const SCHOLARSHIP_PROVIDER_LOGOS = {
  'German Academic Exchange Service': '/images/universities/daad.png',
  'UT Austin AI Lab': '/images/universities/utaustin.png',
  'Government of Ontario / UofT': '/images/universities/utoronto.png',
};

const SCHOLARSHIP_LOGOS_BY_DOMAIN = {
  'adelaide.edu.au': '/images/universities/adelaide.png',
  'uva.nl': '/images/universities/uva.png',
  'anu.edu.au': '/images/universities/anu.png',
  'chalmers.se': '/images/universities/chalmers.png',
  'chevening.org': '/images/universities/chevening.png',
  'msmt.gov.cz': '/images/universities/msmt.png',
  'daad.de': '/images/universities/daad.png',
  'deutschlandstipendium.de': '/images/universities/deutschlandstipendium.png',
  'eacea.ec.europa.eu': '/images/universities/erasmus.png',
  'campusfrance.org': '/images/universities/campusfrance.png',
  'gatescambridge.org': '/images/universities/gatescambridge.png',
  'tudelft.nl': '/images/universities/tudelft.png',
  'kth.se': '/images/universities/kth.png',
  'universiteitleiden.nl': '/images/universities/leiden.png',
  'maastrichtuniversity.nl': '/images/universities/maastricht.png',
  'unimelb.edu.au': '/images/universities/unimelb.png',
  'studyinnl.org': '/images/universities/studyinnl.png',
  'polimi.it': '/images/universities/polimi.svg',
  'ru.nl': '/images/universities/radboud.png',
  'sciencespo.fr': '/images/universities/sciencespo.png',
  'nawa.gov.pl': '/images/universities/nawa.png',
  'si.se': '/images/universities/si.png',
  'turkiyeburslari.gov.tr': '/images/universities/turkiyeburslari.png',
};

const SCHOLARSHIP_LOGOS_BY_NAME = [
  [/stipendium hungaricum/i, '/images/universities/stipendiumhungaricum.png'],
];

export function getScholarshipLogo(scholarship) {
  if (!scholarship) return null;
  const byName = SCHOLARSHIP_LOGOS_BY_NAME.find(([pattern]) => pattern.test(scholarship.name || scholarship.title || ''));
  if (byName) return byName[1];
  let host = '';
  try {
    host = new URL(scholarship.sourceUrl || scholarship.applicationUrl || '').hostname;
  } catch {
    host = '';
  }
  const domain = Object.keys(SCHOLARSHIP_LOGOS_BY_DOMAIN).find((key) => host === key || host.endsWith(`.${key}`));
  return domain ? SCHOLARSHIP_LOGOS_BY_DOMAIN[domain] : SCHOLARSHIP_PROVIDER_LOGOS[scholarship.provider] || null;
}
