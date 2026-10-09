import { useEffect, useRef, type CSSProperties, type HTMLAttributes, type ReactNode } from 'react';

interface GlowCardProps extends Omit<HTMLAttributes<HTMLElement>, 'style' | 'children'> {
  children: ReactNode;
  glowColor?: 'blue' | 'purple' | 'green' | 'red' | 'orange';
  size?: 'sm' | 'md' | 'lg';
  width?: string | number;
  height?: string | number;
  customSize?: boolean;
  style?: CSSProperties & Record<`--${string}`, string | number>;
  as?: 'div' | 'article' | 'section' | 'button';
  type?: 'button' | 'submit' | 'reset';
}

const glowColorMap = {
  blue: { base: 220, spread: 200 },
  purple: { base: 280, spread: 300 },
  green: { base: 120, spread: 200 },
  red: { base: 0, spread: 200 },
  orange: { base: 30, spread: 200 },
};

const sizeMap = {
  sm: 'w-48 h-64',
  md: 'w-64 h-80',
  lg: 'w-80 h-96',
};

const activeCards = new Set<HTMLElement>();
let pointerListenerAttached = false;

function syncPointer(event: PointerEvent) {
  const x = event.clientX;
  const y = event.clientY;

  activeCards.forEach((card) => {
    card.style.setProperty('--x', x.toFixed(2));
    card.style.setProperty('--xp', (x / window.innerWidth).toFixed(3));
    card.style.setProperty('--y', y.toFixed(2));
    card.style.setProperty('--yp', (y / window.innerHeight).toFixed(3));
  });
}

function registerCard(card: HTMLElement) {
  activeCards.add(card);
  if (!pointerListenerAttached) {
    document.addEventListener('pointermove', syncPointer, { passive: true });
    pointerListenerAttached = true;
  }

  return () => {
    activeCards.delete(card);
    if (activeCards.size === 0 && pointerListenerAttached) {
      document.removeEventListener('pointermove', syncPointer);
      pointerListenerAttached = false;
    }
  };
}

export function GlowCard({
  children,
  className = '',
  glowColor = 'blue',
  size = 'md',
  width,
  height,
  customSize = false,
  style,
  as = 'div',
  type = 'button',
  ...elementProps
}: GlowCardProps) {
  const cardRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const card = cardRef.current;
    if (!card) return undefined;
    return registerCard(card);
  }, []);

  const { base, spread } = glowColorMap[glowColor];
  const sizingClasses = customSize ? '' : `${sizeMap[size]} aspect-[3/4] grid grid-rows-[1fr_auto] p-4 gap-4`;
  const hasExistingBackground = Boolean(style?.backgroundColor) || /(?:^|\s)card(?:\s|$)|\bbg-[^\s]+/.test(className);
  const glowStyles = {
    '--base': base,
    '--spread': spread,
    '--radius': '14',
    '--border': '3',
    '--backdrop': 'var(--color-white, hsl(0 0% 100%))',
    '--backup-border': 'var(--color-border, hsl(0 0% 82%))',
    '--size': '200',
    '--outer': '1',
    '--border-size': 'calc(var(--border, 2) * 1px)',
    '--spotlight-size': 'calc(var(--size, 150) * 1px)',
    '--hue': 'calc(var(--base) + (var(--xp, 0) * var(--spread, 0)))',
    backgroundImage: `radial-gradient(
      var(--spotlight-size) var(--spotlight-size) at calc(var(--x, 0) * 1px) calc(var(--y, 0) * 1px),
      hsl(var(--hue, 210) calc(var(--saturation, 100) * 1%) calc(var(--lightness, 70) * 1%) / var(--bg-spot-opacity, 0.12)), transparent
    )`,
      ...(!hasExistingBackground ? { backgroundColor: 'var(--backdrop, transparent)' } : {}),
    backgroundSize: 'calc(100% + (2 * var(--border-size))) calc(100% + (2 * var(--border-size)))',
    backgroundPosition: '50% 50%',
    backgroundAttachment: 'fixed',
    border: 'var(--border-size) solid var(--backup-border)',
    position: 'relative' as const,
    touchAction: 'auto' as const,
    ...style,
    ...(width !== undefined ? { width: typeof width === 'number' ? `${width}px` : width } : {}),
    ...(height !== undefined ? { height: typeof height === 'number' ? `${height}px` : height } : {}),
  } as CSSProperties;
  const CardElement = as;
  const setCardRef = (element: HTMLElement | null) => { cardRef.current = element; };

  return (
    <CardElement
      {...elementProps}
      type={as === 'button' ? type : undefined}
      ref={setCardRef}
      data-glow
      className={`glow-card ${sizingClasses} ${className || ''}`}
      style={glowStyles}
    >
      <div className="glow-card__inner" data-glow aria-hidden="true" />
      {children}
    </CardElement>
  );
}