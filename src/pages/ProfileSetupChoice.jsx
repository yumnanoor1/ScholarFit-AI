import { useNavigate } from 'react-router-dom';
import { FileText, LockKeyhole, UserRound } from 'lucide-react';
import { ChevronSmallRightIcon } from '../components/ui/ChevronSmallRightIcon';
import { GlowCard } from '../components/ui/spotlight-card';

export default function ProfileSetupChoice() {
  const navigate = useNavigate();

  const handleSelectMethod = (method) => {
    if (method === 'manual') {
      navigate('/profile');
    } else if (method === 'cv') {
      navigate('/profile-setup/cv');
    }
  };

  return (
    <div className="profile-method-choice-page flex min-h-[calc(100vh-120px)] w-full items-start justify-center bg-slate-50 dark:bg-slate-950">
      <main className="mx-auto w-full max-w-3xl">
        <header className="profile-method-choice-heading text-center">
          <h1 className="text-2xl font-semibold tracking-tight text-slate-950 dark:text-white sm:text-3xl">
            Build your FitScholar profile
          </h1>
          <p className="text-sm text-slate-600 dark:text-slate-400">
            Choose how you want to get started.
          </p>
        </header>

        <ol aria-label="Profile setup progress" className="profile-method-choice-progress mx-auto flex max-w-lg items-center gap-3 text-xs sm:gap-4 sm:text-sm">
          <li aria-current="step" className="flex shrink-0 items-center gap-2 font-semibold text-sky-800 dark:text-sky-300">
            <span className="flex size-6 items-center justify-center rounded-full bg-sky-700 text-[11px] text-white dark:bg-sky-500">1</span>
            <span>Choose method</span>
          </li>
          <li aria-hidden="true" className="h-px min-w-4 flex-1 bg-slate-300 dark:bg-slate-700" />
          <li className="flex shrink-0 items-center gap-2 text-slate-500 dark:text-slate-400">
            <span className="flex size-6 items-center justify-center rounded-full border border-slate-300 text-[11px] dark:border-slate-700">2</span>
            <span>Complete profile</span>
          </li>
        </ol>

        <div className="grid grid-cols-1 items-stretch gap-5 sm:grid-cols-2 sm:gap-6">
          <GlowCard
            as="button"
            type="button"
            customSize
            onClick={() => handleSelectMethod('manual')}
            aria-label="Build manually"
            className="profile-method-choice-card group flex min-h-[184px] w-full flex-col items-center justify-center rounded-xl border border-slate-200 bg-white text-center shadow-sm transition duration-200 hover:-translate-y-0.5 hover:border-sky-300 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-600 dark:border-slate-800 dark:bg-slate-900 dark:hover:border-sky-700"
          >
            <span className="profile-method-choice-card-icon flex size-10 items-center justify-center rounded-lg bg-sky-50 text-sky-800 transition-transform group-hover:scale-105 dark:bg-sky-950 dark:text-sky-300">
              <UserRound size={20} aria-hidden="true" />
            </span>
            <span className="text-base font-semibold text-slate-900 dark:text-white">Build Profile Manually</span>
            <span className="profile-method-choice-card-action flex w-full items-center justify-center text-sm font-semibold text-sky-800 dark:text-sky-300">
              Build manually <ChevronSmallRightIcon size={16} className="ml-2 transition-transform group-hover:translate-x-1" aria-hidden="true" />
            </span>
          </GlowCard>

          <GlowCard
            as="button"
            type="button"
            customSize
            onClick={() => handleSelectMethod('cv')}
            aria-label="Upload CV"
            className="profile-method-choice-card group relative flex min-h-[184px] w-full flex-col items-center justify-center rounded-xl border border-sky-200 bg-sky-50/70 text-center shadow-md transition duration-200 hover:-translate-y-0.5 hover:border-sky-400 hover:shadow-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-600 dark:border-sky-900 dark:bg-sky-950/45 dark:hover:border-sky-700"
          >
            <span className="profile-method-choice-recommended absolute right-4 top-4 rounded-full bg-emerald-50 text-[9px] font-bold tracking-[0.08em] text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
              RECOMMENDED
            </span>
            <span className="profile-method-choice-card-icon flex size-10 items-center justify-center rounded-lg bg-white text-sky-800 transition-transform group-hover:scale-105 dark:bg-slate-900 dark:text-sky-300">
              <FileText size={20} aria-hidden="true" />
            </span>
            <span className="text-base font-semibold text-slate-900 dark:text-white">Upload your CV</span>
            <span className="profile-method-choice-card-action flex w-full items-center justify-center text-sm font-semibold text-sky-800 dark:text-sky-300">
              Upload CV <ChevronSmallRightIcon size={16} className="ml-2 transition-transform group-hover:translate-x-1" aria-hidden="true" />
            </span>
          </GlowCard>
        </div>

        <p className="profile-method-choice-note flex items-center justify-center gap-2 text-xs text-slate-500 dark:text-slate-400">
          <LockKeyhole size={14} aria-hidden="true" />
          Review and edit before saving.
        </p>
      </main>
    </div>
  );
}