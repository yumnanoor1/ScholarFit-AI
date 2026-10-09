import { useNavigate } from 'react-router-dom';
import { Bookmark } from 'lucide-react';
import { useProfile } from '../context/ProfileContext';
import { ChevronSmallRightIcon } from '../components/ui/ChevronSmallRightIcon';
import { GlowCard } from '../components/ui/spotlight-card';

export default function Dashboard() {
  const navigate = useNavigate();
  const { profile, matchStatistics, isOpportunitySaved, toggleSaveOpportunity } = useProfile();
  const firstName = profile.firstName || (profile.name || '').split(' ')[0] || 'there';
  const profileCompletion = Number(profile.profileCompletionPercentage) || 0;

  const topOpportunities = [
    {
      id: 'chevening',
      name: 'Chevening Scholarship',
      country: 'United Kingdom',
      feasibility: 92,
      eligibility: 'STRONG',
      netCost: '$0',
      deadline: 'Oct 15',
      deadlineDate: '2026-10-15',
      deadlineColor: 'text-red-600 font-bold',
      badgeStyle: 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/50 dark:text-emerald-400 dark:border-emerald-800',
      progressStyle: 'bg-emerald-600'
    },
    {
      id: 'fulbright',
      name: 'Fulbright Student Program',
      country: 'United States',
      feasibility: 84,
      eligibility: 'STRONG',
      netCost: '$0',
      deadline: 'Nov 03',
      deadlineDate: '2026-11-03',
      badgeStyle: 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/50 dark:text-emerald-400 dark:border-emerald-800',
      progressStyle: 'bg-emerald-600'
    },
    {
      id: 'daad',
      name: 'DAAD Research Grant',
      country: 'Germany',
      feasibility: 71,
      eligibility: 'PARTIAL',
      netCost: '$4,200',
      deadline: 'Nov 20',
      deadlineDate: '2026-11-20',
      badgeStyle: 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/50 dark:text-amber-400 dark:border-amber-800',
      progressStyle: 'bg-amber-500'
    },
    {
      id: 'commonwealth',
      name: 'Commonwealth Master\'s Scholarship',
      country: 'Canada',
      feasibility: 68,
      eligibility: 'PARTIAL',
      netCost: '$6,800',
      deadline: 'Dec 07',
      deadlineDate: '2026-12-07',
      badgeStyle: 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/50 dark:text-amber-400 dark:border-amber-800',
      progressStyle: 'bg-amber-500'
    }
  ];

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const opportunitiesWithCountdown = topOpportunities.map((item) => ({
    ...item,
    daysLeft: Math.ceil((new Date(`${item.deadlineDate}T00:00:00`) - today) / 86400000),
  }));
  const nextDeadline = opportunitiesWithCountdown
    .filter((item) => item.daysLeft >= 0)
    .sort((first, second) => first.daysLeft - second.daysLeft)[0];
  return (
    <div className="dashboard-page mx-auto min-h-screen w-full max-w-[1440px]">
      
      {/* 1. Top Header Row with Clear Breathing Room */}
      <div className="dashboard-page-header flex flex-col md:flex-row md:items-center justify-between gap-5">
        <div className="dashboard-greeting">
          <h1 className="text-2xl sm:text-3xl font-semibold text-slate-900 dark:text-white tracking-normal">
            Good morning, {firstName}
          </h1>
          <div className="flex items-center gap-3">
            <span className="text-sm font-medium text-slate-600 dark:text-slate-300">Profile completeness</span>
            <div className="w-40 h-2 bg-slate-200 dark:bg-slate-800 rounded-full overflow-hidden">
              <div role="progressbar" aria-label="Profile completeness" aria-valuemin={0} aria-valuemax={100} aria-valuenow={profileCompletion} className="h-full rounded-full bg-blue-600 transition-[width]" style={{ width: `${profileCompletion}%` }} />
            </div>
            <span className="text-sm font-semibold text-slate-700 dark:text-slate-300">{profileCompletion}%</span>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={() => navigate('/scholarships')}
            className="px-4 py-3 bg-sky-700 hover:bg-sky-800 dark:bg-sky-400 dark:hover:bg-sky-300 dark:text-slate-950 text-white font-semibold text-sm rounded-xl transition shadow-xs"
          >
            Find Scholarships
          </button>
        </div>
      </div>

      {/* 2. Metrics Summary */}
      {profileCompletion === 0 ? (
        <GlowCard as="section" customSize className="dashboard-profile-prompt flex flex-col gap-4 rounded-2xl border border-sky-200 bg-sky-50 shadow-sm dark:border-sky-900 dark:bg-slate-900 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-base font-semibold text-slate-900 dark:text-white">Complete your profile to improve matches</h2>
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">Add your academic, English test, and study preference details to unlock match statistics.</p>
          </div>
          <button
            onClick={() => navigate('/profile-setup')}
            className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg bg-sky-700 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-sky-800 dark:bg-sky-400 dark:text-slate-950 dark:hover:bg-sky-300"
          >
            Complete profile <ChevronSmallRightIcon size={16} className="h-4 w-4" aria-hidden="true" />
          </button>
        </GlowCard>
      ) : (
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="Profile match statistics">
          <GlowCard as="article" customSize className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <p className="text-sm font-medium text-slate-600 dark:text-slate-300">Eligible opportunities</p>
            <p className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">{matchStatistics.eligibleCount}</p>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">Programs and scholarships matching your profile</p>
          </GlowCard>
          <GlowCard as="article" customSize className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <p className="text-sm font-medium text-slate-600 dark:text-slate-300">Funded options</p>
            <p className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">{matchStatistics.fundedCount}</p>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">Eligible funded scholarships</p>
          </GlowCard>
          <GlowCard as="article" customSize className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <p className="text-sm font-medium text-slate-600 dark:text-slate-300">Median listed tuition</p>
            <p className="mt-2 text-xl font-semibold text-slate-900 dark:text-white">{matchStatistics.medianTuition}</p>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">Across matched programs</p>
          </GlowCard>
          <GlowCard as="article" customSize className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <p className="text-sm font-medium text-slate-600 dark:text-slate-300">Next deadline</p>
            <p className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">{nextDeadline ? (nextDeadline.daysLeft === 0 ? 'Today' : `${nextDeadline.daysLeft} days`) : 'None upcoming'}</p>
            {nextDeadline && <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{nextDeadline.name} · {nextDeadline.deadline}</p>}
          </GlowCard>
        </section>
      )}

      {/* 3. Full-Width Opportunities Table */}
      <div className="dashboard-opportunities mx-auto w-full max-w-6xl">
        <div className="flex min-h-12 flex-wrap items-center justify-between gap-4 px-1">
          <h2 className="text-2xl font-semibold text-slate-900 dark:text-white">Top opportunities</h2>
          <button 
            onClick={() => navigate('/scholarships')} 
            className="inline-flex items-center gap-1 whitespace-nowrap text-sm font-semibold text-blue-600 transition-colors hover:text-blue-700 dark:text-blue-400"
          >
            View all matching <ChevronSmallRightIcon size={15} aria-hidden="true" />
          </button>
        </div>

        <div className="grid grid-cols-1 gap-4 xl:hidden">
          {opportunitiesWithCountdown.map((item) => (
            <GlowCard as="article" key={item.id} customSize className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900 sm:p-6">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="text-sm font-semibold leading-5 text-slate-900 dark:text-white">{item.name}</h3>
                  <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">{item.country}</p>
                </div>
                <span className={`shrink-0 rounded-md border px-2 py-1 text-[10px] font-bold ${item.badgeStyle}`}>
                  {item.eligibility}
                </span>
              </div>

              <div className="mt-5 grid grid-cols-2 gap-5">
                <div>
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-slate-600 dark:text-slate-400">Feasibility</span>
                    <span className="font-semibold text-slate-900 dark:text-white">{item.feasibility}%</span>
                  </div>
                  <div role="progressbar" aria-label={`${item.name} feasibility`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={item.feasibility} className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                    <div className={`h-full ${item.progressStyle}`} style={{ width: `${item.feasibility}%` }} />
                  </div>
                </div>
                <div className="text-right">
                  <p className="text-xs text-slate-600 dark:text-slate-400">Net cost</p>
                  <p className="mt-1 text-sm font-semibold text-slate-900 dark:text-white">{item.netCost}</p>
                </div>
              </div>

              <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4 dark:border-slate-800">
                <p className={`text-xs font-medium ${item.daysLeft <= 7 ? 'text-red-600 dark:text-red-400' : 'text-slate-600 dark:text-slate-400'}`}>
                  {item.deadline} · {item.daysLeft === 0 ? 'Due today' : `${item.daysLeft} days left`}
                </p>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    aria-pressed={isOpportunitySaved(item.id)}
                    aria-label={`${isOpportunitySaved(item.id) ? 'Unsave' : 'Save'} ${item.name}`}
                    onClick={() => toggleSaveOpportunity(item.id)}
                    className="rounded-md border border-slate-200 p-2 text-slate-600 transition hover:border-sky-300 hover:text-sky-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-600 dark:border-slate-700 dark:text-slate-300 dark:hover:text-sky-300"
                  >
                    <Bookmark size={15} fill={isOpportunitySaved(item.id) ? 'currentColor' : 'none'} aria-hidden="true" />
                  </button>
                  <button type="button" onClick={() => navigate('/pathway')} className="inline-flex items-center gap-1 rounded-md border border-slate-200 px-2.5 py-2 text-xs font-semibold text-slate-700 hover:border-sky-300 hover:text-sky-700 dark:border-slate-700 dark:text-slate-200 dark:hover:text-sky-300">
                    View <ChevronSmallRightIcon size={13} aria-hidden="true" />
                  </button>
                </div>
              </div>
            </GlowCard>
          ))}
        </div>

        <GlowCard customSize className="hidden overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900 xl:block">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50/80 dark:bg-slate-950/50 text-slate-600 dark:text-slate-300 uppercase tracking-wider font-semibold border-b border-slate-100 dark:border-slate-800">
                <tr>
                  <th className="px-7 py-5">Name</th>
                  <th className="px-7 py-5">Country</th>
                  <th className="px-7 py-5">Feasibility</th>
                  <th className="px-7 py-5">Eligibility</th>
                  <th className="px-7 py-5">Net Cost</th>
                  <th className="px-7 py-5 text-right">Deadline</th>
                  <th className="px-7 py-5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800 text-slate-700 dark:text-slate-200 font-medium">
                {opportunitiesWithCountdown.map((item) => (
                  <tr
                    key={item.id}
                    className="transition-colors hover:bg-slate-50/70 dark:hover:bg-slate-800/40"
                  >
                    <td className="px-7 py-6 font-semibold text-slate-900 dark:text-white">{item.name}</td>
                    <td className="px-7 py-6 text-slate-500 dark:text-slate-400">{item.country}</td>
                    <td className="px-7 py-6">
                      <div className="flex items-center gap-3">
                        <span title="Estimated from academic, language, and program requirements" className="font-bold text-slate-900 dark:text-white" aria-label={`Feasibility score ${item.feasibility} percent; based on academic, language, and program requirements`}>{item.feasibility}</span>
                        <div role="progressbar" aria-label={`${item.name} feasibility`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={item.feasibility} title="Estimated from academic, language, and program requirements" className="w-16 h-1.5 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
                          <div className={`h-full ${item.progressStyle}`} style={{ width: `${item.feasibility}%` }}></div>
                        </div>
                      </div>
                    </td>
                    <td className="px-7 py-6">
                      <span className={`px-2.5 py-1 text-[10px] font-bold rounded-md border ${item.badgeStyle}`}>
                        • {item.eligibility}
                      </span>
                    </td>
                    <td className="px-7 py-6 font-semibold">{item.netCost}</td>
                    <td className={`px-7 py-6 text-right ${item.daysLeft <= 7 ? 'text-red-600 dark:text-red-400' : 'text-slate-700 dark:text-slate-300'}`}>
                      <span className="font-semibold">{item.deadline}</span>
                      <span className="mt-1 block text-xs font-medium">{item.daysLeft === 0 ? 'Due today' : `${item.daysLeft} days left`}</span>
                    </td>
                    <td className="px-7 py-6">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          type="button"
                          aria-pressed={isOpportunitySaved(item.id)}
                          aria-label={`${isOpportunitySaved(item.id) ? 'Unsave' : 'Save'} ${item.name}`}
                          onClick={() => toggleSaveOpportunity(item.id)}
                          className="rounded-md border border-slate-200 p-2 text-slate-600 transition hover:border-sky-300 hover:text-sky-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-600 dark:border-slate-700 dark:text-slate-300 dark:hover:text-sky-300"
                        >
                          <Bookmark size={15} fill={isOpportunitySaved(item.id) ? 'currentColor' : 'none'} aria-hidden="true" />
                        </button>
                        <button
                          type="button"
                          onClick={() => navigate('/pathway')}
                          className="inline-flex items-center gap-1 rounded-md border border-slate-200 px-2.5 py-2 text-xs font-semibold text-slate-700 transition hover:border-sky-300 hover:text-sky-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-600 dark:border-slate-700 dark:text-slate-200 dark:hover:text-sky-300"
                        >
                          View <ChevronSmallRightIcon size={13} aria-hidden="true" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </GlowCard>
      </div>

    </div>
  );
}