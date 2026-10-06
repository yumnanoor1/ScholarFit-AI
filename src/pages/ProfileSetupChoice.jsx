import { useNavigate } from 'react-router-dom';
import { FileUp, UserRound } from 'lucide-react';
import { Button } from '@/components/ui/button';
import PageHeader from '@/components/layout/PageHeader';

export default function ProfileSetupChoice() {
  const navigate = useNavigate();

  return (
    <div className="page-container" style={{ maxWidth: '1000px', paddingTop: '36px' }}>
      <PageHeader
        title="How would you like to build your profile?"
        subtitle="Choose how you'd like to provide your information. You can build your profile manually or upload your CV and let FitScholar AI extract the information for you."
      />

      <div className="mt-8 grid grid-cols-1 gap-5 md:grid-cols-2">
        <article className="flex min-h-64 flex-col rounded-lg border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <span className="mb-5 flex size-11 items-center justify-center rounded-md bg-sky-50 text-sky-800 dark:bg-sky-950 dark:text-sky-200">
            <UserRound size={21} aria-hidden="true" />
          </span>
          <h2 className="text-lg font-semibold text-slate-950 dark:text-slate-50">Build Profile</h2>
          <p className="mt-2 flex-1 text-sm leading-6 text-slate-600 dark:text-slate-400">
            Enter your academic, English proficiency, and study preferences manually.
          </p>
          <Button className="mt-6 w-fit" onClick={() => navigate('/profile?edit=1&step=0&method=manual')}>
            Build Manually
          </Button>
        </article>

        <article className="flex min-h-64 flex-col rounded-lg border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <span className="mb-5 flex size-11 items-center justify-center rounded-md bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">
            <FileUp size={21} aria-hidden="true" />
          </span>
          <h2 className="text-lg font-semibold text-slate-950 dark:text-slate-50">Upload CV</h2>
          <p className="mt-2 flex-1 text-sm leading-6 text-slate-600 dark:text-slate-400">
            Upload your CV and FitScholar AI will extract relevant information to pre-fill your profile.
          </p>
          <Button variant="outline" className="mt-6 w-fit" onClick={() => navigate('/profile-setup/cv')}>
            Upload CV
          </Button>
        </article>
      </div>

      <p className="mt-5 text-center text-xs text-slate-500 dark:text-slate-400">
        You can review and edit all extracted information before saving your profile.
      </p>
    </div>
  );
}