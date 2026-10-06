"use client";

import { ArrowRight, Check, GraduationCap, Globe, Wallet } from "lucide-react";
import { motion, useReducedMotion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface SplashScreenProps {
    title?: string;
    onExplore?: () => void;
    onLogin?: () => void;
    onRegister?: () => void;
}

const previewItems = [
    { icon: GraduationCap, label: "Study level", value: "Master's degree" },
    { icon: Globe, label: "Destinations", value: "Europe and beyond" },
    { icon: Wallet, label: "Funding", value: "Scholarships and aid" },
];

export function BackgroundPaths({
    title = "FitScholar AI",
    onExplore,
    onLogin,
    onRegister,
}: SplashScreenProps) {
    const reduceMotion = useReducedMotion();

    return (
        <main className="relative min-h-screen overflow-hidden bg-[#050609] text-white selection:bg-cyan-300/30">
            <div className="pointer-events-none absolute inset-0" aria-hidden="true">
                <div className="splash-grid absolute inset-0 opacity-30" />
                <motion.div
                    className="absolute inset-x-0 top-[42%] h-48 bg-gradient-to-r from-transparent via-cyan-400/15 to-transparent blur-3xl"
                    animate={reduceMotion ? undefined : { x: ["-35%", "35%", "-35%"], opacity: [0.25, 0.65, 0.25] }}
                    transition={{ duration: 14, ease: "easeInOut", repeat: Infinity }}
                />
                <div className="absolute inset-x-0 bottom-0 h-[45%] bg-gradient-to-t from-violet-950/35 via-transparent to-transparent" />
            </div>

            <div className="relative z-10 mx-auto flex min-h-screen w-full max-w-[1440px] flex-col px-5 sm:px-8 lg:px-12">
                <header className="flex h-[76px] shrink-0 items-center justify-between border-b border-white/10">
                    <a href="/" onClick={(event) => { event.preventDefault(); onExplore?.(); }} className="flex items-center gap-3" aria-label={`${title} home`}>
                        <span className="flex size-9 items-center justify-center rounded-lg border border-white/10 bg-white/[0.06] text-cyan-200">
                            <GraduationCap size={19} aria-hidden="true" />
                        </span>
                        <span className="text-sm font-semibold tracking-wide text-white">{title}</span>
                    </a>
                    <nav className="flex items-center gap-2 sm:gap-3" aria-label="Splash navigation">
                        <Button variant="ghost" onClick={onLogin} className="h-9 px-3 text-sm text-slate-300 hover:bg-white/10 hover:text-white sm:px-4">
                            Sign in
                        </Button>
                        <Button onClick={onRegister || onExplore} className="h-9 rounded-md bg-cyan-300 px-3 text-sm font-semibold text-slate-950 hover:bg-cyan-200 sm:px-4">
                            Create profile
                        </Button>
                    </nav>
                </header>

                <section className="grid flex-1 items-center gap-12 py-12 lg:grid-cols-[0.9fr_1.1fr] lg:gap-16 lg:py-16">
                    <motion.div
                        initial={reduceMotion ? false : { opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.7, ease: "easeOut" }}
                        className="max-w-xl"
                    >
                        <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-cyan-300/20 bg-cyan-300/[0.07] px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-200">
                            <span className="size-1.5 rounded-full bg-cyan-300" />
                            Master's study planner
                        </div>
                        <h1 className="max-w-[12ch] text-4xl font-semibold leading-[1.06] tracking-tight text-white sm:text-5xl lg:text-6xl">
                            Plan your next chapter with clarity.
                        </h1>
                        <p className="mt-6 max-w-lg text-base leading-7 text-slate-300 sm:text-lg">
                            Find Master's programs, scholarships, and funding paths shaped around your academic profile.
                        </p>
                        <div className="mt-8 flex flex-col gap-3 sm:flex-row">
                            <Button onClick={onRegister || onExplore} className="h-11 justify-center rounded-md bg-cyan-300 px-5 font-semibold text-slate-950 hover:bg-cyan-200">
                                Start your profile <ArrowRight size={17} aria-hidden="true" />
                            </Button>
                            <Button variant="outline" onClick={onExplore} className="h-11 justify-center rounded-md border-white/20 bg-white/[0.03] px-5 text-white hover:bg-white/10 hover:text-white">
                                Explore FitScholar
                            </Button>
                        </div>
                        <p className="mt-5 text-xs text-slate-500">A focused workspace for Master's admissions and funding.</p>
                    </motion.div>

                    <motion.div
                        initial={reduceMotion ? false : { opacity: 0, y: 24, scale: 0.985 }}
                        animate={{ opacity: 1, y: 0, scale: 1 }}
                        transition={{ duration: 0.9, delay: reduceMotion ? 0 : 0.15, ease: "easeOut" }}
                        className="relative mx-auto w-full max-w-[650px]"
                    >
                        <div className="absolute -inset-px rounded-xl bg-gradient-to-br from-cyan-300/40 via-violet-500/20 to-transparent blur-sm" aria-hidden="true" />
                        <div className="relative overflow-hidden rounded-xl border border-white/10 bg-[#080a10]/95 shadow-2xl shadow-black/50">
                            <div className="flex h-12 items-center justify-between border-b border-white/[0.08] px-4 sm:px-5">
                                <div className="flex items-center gap-2">
                                    <span className="size-2 rounded-full bg-cyan-300" />
                                    <span className="text-xs font-medium text-slate-200">FitScholar workspace</span>
                                </div>
                                <span className="text-[10px] uppercase tracking-[0.12em] text-slate-500">Master's overview</span>
                            </div>

                            <div className="grid gap-0 md:grid-cols-[1fr_0.88fr]">
                                <div className="p-5 sm:p-7">
                                    <div className="flex items-start justify-between gap-4">
                                        <div>
                                            <p className="text-xs text-slate-500">Your study plan</p>
                                            <h2 className="mt-1 text-lg font-semibold text-white sm:text-xl">A profile built around you</h2>
                                        </div>
                                        <span className="rounded-md border border-cyan-300/20 bg-cyan-300/[0.08] px-2 py-1 text-[10px] font-medium text-cyan-200">READY TO START</span>
                                    </div>

                                    <div className="mt-7 space-y-3">
                                        {previewItems.map(({ icon: Icon, label, value }, index) => (
                                            <div key={label} className="flex items-center gap-3 border-b border-white/[0.07] pb-3 last:border-0">
                                                <span className={cn("flex size-9 shrink-0 items-center justify-center rounded-md", index === 0 ? "bg-violet-400/10 text-violet-200" : index === 1 ? "bg-cyan-300/10 text-cyan-200" : "bg-blue-400/10 text-blue-200")}>
                                                    <Icon size={17} aria-hidden="true" />
                                                </span>
                                                <div className="min-w-0 flex-1">
                                                    <p className="text-[11px] text-slate-500">{label}</p>
                                                    <p className="mt-0.5 truncate text-sm font-medium text-slate-200">{value}</p>
                                                </div>
                                                <Check size={16} className="text-cyan-300/70" aria-hidden="true" />
                                            </div>
                                        ))}
                                    </div>

                                    <div className="mt-5 rounded-md border border-white/[0.08] bg-white/[0.03] p-3.5">
                                        <p className="text-[11px] font-medium text-slate-400">Recommendations consider</p>
                                        <p className="mt-1.5 text-xs leading-5 text-slate-300">Academic fit · language requirements · funding · affordability</p>
                                    </div>
                                </div>

                                <div className="relative flex min-h-52 flex-col justify-between overflow-hidden border-t border-white/[0.08] bg-gradient-to-br from-[#101626] to-[#090b12] p-5 md:border-l md:border-t-0 sm:p-7">
                                    <div className="absolute inset-0 opacity-30" aria-hidden="true" style={{ backgroundImage: "linear-gradient(rgba(148,163,184,0.16) 1px, transparent 1px), linear-gradient(90deg, rgba(148,163,184,0.16) 1px, transparent 1px)", backgroundSize: "28px 28px", maskImage: "linear-gradient(to bottom right, black, transparent 90%)" }} />
                                    <div className="relative">
                                        <p className="text-xs text-slate-500">From planning to applications</p>
                                        <div className="mt-5 space-y-3">
                                            {["Build your profile", "Compare Master's programs", "Explore funding options"].map((item, index) => (
                                                <div key={item} className="flex items-center gap-3">
                                                    <span className={cn("flex size-6 items-center justify-center rounded-full border text-[10px]", index === 0 ? "border-cyan-300/50 bg-cyan-300/10 text-cyan-200" : "border-white/10 bg-white/[0.03] text-slate-500")}>
                                                        0{index + 1}
                                                    </span>
                                                    <span className={cn("text-xs", index === 0 ? "text-slate-100" : "text-slate-500")}>{item}</span>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                    <div className="relative mt-7 flex items-center justify-between border-t border-white/[0.08] pt-4">
                                        <span className="text-[11px] text-slate-500">One guided workspace</span>
                                        <span className="text-xs font-medium text-cyan-200">Explore <ArrowRight size={13} className="ml-1 inline" aria-hidden="true" /></span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </motion.div>
                </section>

                <footer className="flex min-h-12 items-center justify-between border-t border-white/10 py-3 text-[11px] text-slate-500">
                    <span>FitScholar AI</span>
                    <span>Master's admissions · Scholarships · Funding</span>
                </footer>
            </div>
        </main>
    );
}