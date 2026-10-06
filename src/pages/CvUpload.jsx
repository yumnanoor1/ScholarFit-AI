import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertCircle, CheckCircle2, FileText, FileUp, RotateCw, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import PageHeader from '@/components/layout/PageHeader';
import { useAuth } from '../context/AuthContext';
import { useProfile } from '../context/ProfileContext';
import { extractProfileFromCv } from '../services/profileExtraction';

const MAX_FILE_SIZE = 20 * 1024 * 1024;
const ACCEPTED_EXTENSIONS = ['pdf', 'doc', 'docx'];
const PROCESSING_STEPS = [
  'Reading CV',
  'Extracting personal information',
  'Extracting academic information',
  'Extracting skills and experience',
  'Preparing profile',
];

function formatFileSize(bytes) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function wait(duration) {
  return new Promise((resolve) => window.setTimeout(resolve, duration));
}

export default function CvUpload() {
  const navigate = useNavigate();
  const inputRef = useRef(null);
  const { user } = useAuth();
  const { saveCvUpload, saveExtractedProfile } = useProfile();
  const [file, setFile] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [processingStep, setProcessingStep] = useState(-1);
  const [error, setError] = useState('');

  const selectFile = (selectedFile) => {
    if (!selectedFile) return;
    const extension = selectedFile.name.split('.').pop()?.toLowerCase();
    if (!ACCEPTED_EXTENSIONS.includes(extension)) {
      setError('Choose a PDF, DOC, or DOCX file.');
      setFile(null);
      return;
    }
    if (selectedFile.size === 0) {
      setError('The selected file is empty. Choose a CV with readable content.');
      setFile(null);
      return;
    }
    if (selectedFile.size > MAX_FILE_SIZE) {
      setError('CV files must be 20 MB or smaller.');
      setFile(null);
      return;
    }
    setError('');
    setFile(selectedFile);
  };

  const handleExtract = async () => {
    if (!file) return;
    setProcessing(true);
    setError('');
    const fileInfo = {
      name: file.name,
      type: file.type || file.name.split('.').pop()?.toUpperCase(),
      size: file.size,
      uploadedAt: new Date().toISOString(),
    };
    saveCvUpload(fileInfo);

    try {
      for (let index = 0; index < PROCESSING_STEPS.length - 1; index += 1) {
        setProcessingStep(index);
        await wait(240);
      }
      const extraction = await extractProfileFromCv(file, { user });
      setProcessingStep(PROCESSING_STEPS.length - 1);
      await wait(180);
      saveExtractedProfile({
        extractedProfile: extraction.profile,
        fieldStatuses: extraction.fieldStatuses,
        fileInfo: { ...fileInfo, extractionSource: extraction.source },
      });
      navigate('/profile/verify');
    } catch (processingError) {
      setError(processingError?.message || 'We could not analyze this CV. Please try again or build your profile manually.');
      setProcessing(false);
    }
  };

  return (
    <div className="page-container" style={{ maxWidth: '900px', paddingTop: '36px' }}>
      <PageHeader
        title={processing ? 'Analyzing Your CV' : 'Upload Your CV'}
        subtitle={processing ? 'Preparing a draft from information found in your document.' : "We'll extract relevant information from your CV to help complete your Master's profile."}
      />

      {processing ? (
        <section className="mt-7 rounded-lg border border-slate-200 bg-white p-6 dark:border-slate-800 dark:bg-slate-900" aria-live="polite">
          <div className="flex items-center gap-3">
            <RotateCw size={20} className="animate-spin text-sky-700 dark:text-sky-300" aria-hidden="true" />
            <h2 className="font-semibold text-slate-900 dark:text-slate-100">Analyzing Your CV</h2>
          </div>
          <ol className="mt-6 space-y-4">
            {PROCESSING_STEPS.map((step, index) => (
              <li key={step} className="flex items-center gap-3 text-sm">
                {index < processingStep ? <CheckCircle2 size={18} className="text-emerald-600" aria-hidden="true" /> : index === processingStep ? <RotateCw size={18} className="animate-spin text-sky-700" aria-hidden="true" /> : <span className="size-[18px] rounded-full border border-slate-300 dark:border-slate-700" aria-hidden="true" />}
                <span className={index <= processingStep ? 'text-slate-900 dark:text-slate-100' : 'text-slate-500'}>{step}</span>
              </li>
            ))}
          </ol>
        </section>
      ) : (
        <>
          <div
            onDragEnter={(event) => { event.preventDefault(); setDragging(true); }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={(event) => { event.preventDefault(); setDragging(false); }}
            onDrop={(event) => { event.preventDefault(); setDragging(false); selectFile(event.dataTransfer.files?.[0]); }}
            className={`mt-7 rounded-lg border-2 border-dashed p-7 text-center transition-colors sm:p-10 ${dragging ? 'border-sky-600 bg-sky-50 dark:bg-sky-950/40' : 'border-slate-300 bg-white dark:border-slate-700 dark:bg-slate-900'}`}
          >
            <span className="mx-auto flex size-12 items-center justify-center rounded-md bg-sky-50 text-sky-800 dark:bg-sky-950 dark:text-sky-200">
              <FileUp size={23} aria-hidden="true" />
            </span>
            <h2 className="mt-4 font-semibold text-slate-900 dark:text-slate-100">Drag &amp; drop your CV here</h2>
            <p className="mt-1 text-sm text-slate-500">or browse for a file</p>
            <input ref={inputRef} id="cv-picker" type="file" accept=".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={(event) => selectFile(event.currentTarget.files?.[0])} className="sr-only" />
            <label htmlFor="cv-picker" className="mt-5 inline-flex h-10 cursor-pointer items-center justify-center rounded-md border border-slate-300 px-4 text-sm font-medium text-slate-800 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-100 dark:hover:bg-slate-800">
              Browse Files
            </label>
            <p className="mt-4 text-xs text-slate-500">PDF, DOC, or DOCX · Maximum 20 MB</p>
          </div>

          {file && (
            <div className="mt-4 flex flex-wrap items-center gap-3 rounded-md border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
              <FileText size={20} className="shrink-0 text-slate-500" aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">{file.name}</p>
                <p className="mt-0.5 text-xs text-slate-500">{file.name.split('.').pop()?.toUpperCase()} · {formatFileSize(file.size)}</p>
              </div>
              <label htmlFor="cv-picker" onClick={() => { if (inputRef.current) inputRef.current.value = ''; }} className="cursor-pointer text-sm font-medium text-sky-800 hover:underline dark:text-sky-300">Replace file</label>
              <button type="button" onClick={() => { setFile(null); setError(''); if (inputRef.current) inputRef.current.value = ''; }} className="inline-flex items-center gap-1 text-sm text-slate-600 hover:text-red-700 dark:text-slate-300 dark:hover:text-red-300">
                <Trash2 size={16} aria-hidden="true" /> Remove file
              </button>
            </div>
          )}

          {error && <p role="alert" className="mt-4 flex items-center gap-2 text-sm text-red-700 dark:text-red-300"><AlertCircle size={17} />{error}</p>}
          <p className="mt-4 text-xs leading-5 text-slate-500">You will review and edit all extracted details. Fields not found in the document will be left blank.</p>
          <div className="mt-6 flex justify-between gap-3">
            <Button type="button" variant="outline" onClick={() => navigate('/profile-setup')}>Back</Button>
            <Button type="button" disabled={!file} onClick={handleExtract}>Extract Information</Button>
          </div>
        </>
      )}
    </div>
  );
}