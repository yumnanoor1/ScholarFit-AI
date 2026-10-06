import React from "react";
import { motion, useReducedMotion } from "framer-motion";
import { cn } from "@/lib/utils";

interface AuroraHeroProps {
  title?: string;
  description?: string;
  primaryAction?: {
    label: string;
    onClick: () => void;
  };
  secondaryAction?: {
    label: string;
    onClick: () => void;
  };
  className?: string;
  children?: React.ReactNode;
}

export function AuroraHero({
  title,
  description,
  primaryAction,
  secondaryAction,
  className,
  children,
}: AuroraHeroProps) {
  const prefersReducedMotion = useReducedMotion();
  const titleWords = title?.split(" ") || [];

  return (
    <section
      className={cn(
        "relative flex min-h-screen w-full items-center justify-center overflow-hidden bg-background",
        className,
      )}
      role="banner"
      aria-label="Hero section"
    >
      <div className="absolute inset-0 overflow-hidden opacity-40" aria-hidden="true">
        <motion.div
          className="absolute inset-[-100%]"
          style={{
            background: `
              repeating-linear-gradient(100deg,
                #8b5cf6 10%,
                #3b82f6 15%,
                #ec4899 20%,
                #8b5cf6 25%,
                #3b82f6 30%)
            `,
            backgroundSize: "300% 100%",
            filter: "blur(80px)",
          }}
          animate={prefersReducedMotion ? undefined : { backgroundPosition: ["0% 50%", "100% 50%", "0% 50%"] }}
          transition={{ duration: 20, repeat: Infinity, ease: "linear" }}
        />
        <motion.div
          className="absolute inset-[-10px]"
          style={{
            background: `
              repeating-linear-gradient(100deg,
                rgba(139, 92, 246, 0.1) 0%,
                rgba(139, 92, 246, 0.1) 7%,
                transparent 10%,
                transparent 12%,
                rgba(139, 92, 246, 0.1) 16%),
              repeating-linear-gradient(100deg,
                #8b5cf6 10%,
                #3b82f6 15%,
                #ec4899 20%,
                #8b5cf6 25%,
                #3b82f6 30%)
            `,
            backgroundSize: "200%, 100%",
            backgroundPosition: "50% 50%, 50% 50%",
            mixBlendMode: "difference",
          }}
          animate={prefersReducedMotion ? undefined : {
            backgroundPosition: [
              "50% 50%, 50% 50%",
              "100% 50%, 150% 50%",
              "50% 50%, 50% 50%",
            ],
          }}
          transition={{ duration: 15, repeat: Infinity, ease: "linear" }}
        />
      </div>

      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background: "radial-gradient(ellipse at center, transparent 0%, rgba(0, 0, 0, 0.8) 100%)",
        }}
        aria-hidden="true"
      />

      {children ? (
        <div className="relative z-10 w-full">{children}</div>
      ) : (
        <div className="container relative z-10 mx-auto px-4 text-center md:px-6">
          <motion.div
            initial={prefersReducedMotion ? false : { opacity: 0, y: 50 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 1.2, ease: "easeOut" }}
            className="mx-auto max-w-5xl"
          >
            {title && (
              <h1 className="mb-8 text-5xl font-bold tracking-tight sm:text-6xl md:text-7xl lg:text-8xl">
                {titleWords.map((word, wordIndex) => (
                  <span key={`${word}-${wordIndex}`} className="mb-2 mr-3 inline-block last:mr-0 sm:mr-4">
                    {word.split("").map((letter, letterIndex) => (
                      <motion.span
                        key={`${wordIndex}-${letterIndex}`}
                        initial={prefersReducedMotion ? false : { y: 60, opacity: 0, filter: "blur(8px)" }}
                        animate={{ y: 0, opacity: 1, filter: "blur(0px)" }}
                        transition={{
                          delay: prefersReducedMotion ? 0 : wordIndex * 0.08 + letterIndex * 0.02,
                          type: "spring",
                          stiffness: 100,
                          damping: 15,
                        }}
                        className="inline-block cursor-default bg-gradient-to-br from-white via-white/90 to-white/70 bg-clip-text text-transparent"
                        style={{ textShadow: "0 0 20px hsl(var(--primary) / 0.3)" }}
                      >
                        {letter}
                      </motion.span>
                    ))}
                  </span>
                ))}
              </h1>
            )}

            {description && (
              <motion.p
                initial={prefersReducedMotion ? false : { opacity: 0, y: 30 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 1, delay: prefersReducedMotion ? 0 : 0.6 }}
                className="mx-auto mb-10 max-w-3xl text-lg leading-relaxed text-white/80 sm:text-xl md:text-2xl"
              >
                {description}
              </motion.p>
            )}

            {(primaryAction || secondaryAction) && (
              <motion.div
                initial={prefersReducedMotion ? false : { opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ duration: 0.8, delay: prefersReducedMotion ? 0 : 1 }}
                className="flex flex-col items-center justify-center gap-4 sm:flex-row"
              >
                {primaryAction && (
                  <button
                    onClick={primaryAction.onClick}
                    className="rounded-full bg-primary px-8 py-4 text-base font-semibold text-primary-foreground shadow-lg transition-all duration-300 hover:bg-primary/90 hover:shadow-xl focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 focus:ring-offset-background sm:text-lg"
                  >
                    {primaryAction.label}
                  </button>
                )}
                {secondaryAction && (
                  <button
                    onClick={secondaryAction.onClick}
                    className="rounded-full bg-secondary px-8 py-4 text-base font-semibold text-secondary-foreground shadow-lg transition-all duration-300 hover:bg-secondary/90 hover:shadow-xl focus:outline-none focus:ring-2 focus:ring-secondary focus:ring-offset-2 focus:ring-offset-background sm:text-lg"
                  >
                    {secondaryAction.label}
                  </button>
                )}
              </motion.div>
            )}
          </motion.div>
        </div>
      )}
    </section>
  );
}