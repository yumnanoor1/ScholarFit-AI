import { Link } from 'react-router-dom';
import BrandLogo from '../common/BrandLogo';
import { Ripple, TechOrbitDisplay } from '../ui/modern-animated-sign-in';

// University logos orbiting the headline: three rings, items spaced evenly on each ring.
// Inner radius clears the headline so logos orbit around it, not across it.
const ORBIT_RINGS = [
  { radius: 185, size: 'size-[40px]', reverse: false, logos: ['tum', 'eth', 'kth'] },
  { radius: 250, size: 'size-[44px]', reverse: true, logos: ['tudelft', 'aalto', 'polimi', 'tuwien'] },
  { radius: 315, size: 'size-[48px]', reverse: false, logos: ['saarland', 'ipparis', 'elte'] },
];
const ORBIT_DURATION = 36;
const LOGO_FILES = { polimi: 'polimi.svg' };

const orbitIcons = ORBIT_RINGS.flatMap((ring, ringIndex) => ring.logos.map((key, index) => ({
  component: () => (
    <span className="grid size-full place-items-center rounded-xl bg-white p-1.5 shadow-lg shadow-black/25">
      <img
        src={`/images/universities/${LOGO_FILES[key] || `${key}.png`}`}
        alt=""
        className="max-h-full max-w-full rounded-md object-contain"
        draggable="false"
      />
    </span>
  ),
  className: `${ring.size} border-none bg-transparent`,
  radius: ring.radius,
  duration: ORBIT_DURATION,
  // Rings start a sixth of a turn apart so their first logos don't line up
  delay: (ORBIT_DURATION / ring.logos.length) * index + (ORBIT_DURATION / 6) * ringIndex,
  reverse: ring.reverse,
  path: index === 0, // draw each ring's path once
})));

/** Navy left panel used by Login, Forgot password and Reset password (hidden below lg). */
export default function AuthBrandPanel() {
  return (
    <aside className="relative hidden min-h-[100dvh] w-1/2 flex-col overflow-hidden bg-gradient-to-br from-(--brand-navy) to-(--brand-navy-light) lg:flex">
      <Ripple
        mainCircleSize={120}
        className="max-w-none bg-transparent"
        circleClassName="bg-(--brand-sky)/10 border-(--brand-sky)/30"
      />
      <div className="login-orbit">
        <TechOrbitDisplay
          iconsArray={orbitIcons}
          pathClassName="stroke-white/15"
          centerContent={(
            <Link to="/" aria-label="FitScholars home" className="block rounded-xl">
              <BrandLogo tone="light" height={120} alt="" />
            </Link>
          )}
        />
      </div>
    </aside>
  );
}
