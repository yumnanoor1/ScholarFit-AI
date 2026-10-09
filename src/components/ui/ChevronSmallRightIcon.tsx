import type { SVGProps } from 'react';

type ChevronSmallRightIconProps = SVGProps<SVGSVGElement> & { size?: number };

export function ChevronSmallRightIcon({ size = 24, ...props }: ChevronSmallRightIconProps) {
  return (
    <svg width={size} height={size} xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" {...props}>
      <path
        fill="none"
        stroke="currentColor"
        strokeDasharray="10"
        strokeDashoffset="10"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="M15 12l-5 -5M15 12l-5 5"
      >
        <animate attributeName="stroke-dashoffset" from="10" to="0" dur="0.4s" fill="freeze" />
      </path>
    </svg>
  );
}