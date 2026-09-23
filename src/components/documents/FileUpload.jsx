import React, { useState } from 'react';
import { UploadCloud, FileText, CheckCircle2 } from 'lucide-react';

export default function FileUpload({ onUpload, isUploading = false }) {
  const [selectedFile, setSelectedFile] = useState(null);

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files[0]) {
      setSelectedFile(e.target.files[0]);
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (selectedFile && onUpload) {
      onUpload(selectedFile);
      setSelectedFile(null);
    }
  };

  return (
    <div className="card" style={{ textAlign: 'center', borderStyle: 'dashed', borderWidth: '2px', padding: '36px 20px' }}>
      <UploadCloud size={44} color="var(--color-primary)" style={{ marginBottom: '12px' }} />
      <h3 style={{ fontSize: '1.1rem', color: 'var(--color-dark)', marginBottom: '6px' }}>Upload Academic Document</h3>
      <p style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)', marginBottom: '20px' }}>
        Select your official Transcript, CV, or English Proficiency Score Card (PDF/DOCX)
      </p>

      <form onSubmit={handleSubmit} style={{ display: 'inline-block' }}>
        <input 
          type="file" 
          id="academic-file-input" 
          accept=".pdf,.docx,.doc" 
          onChange={handleFileChange} 
          style={{ display: 'none' }} 
        />
        
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center', justifyContent: 'center', flexWrap: 'wrap' }}>
          <label 
            htmlFor="academic-file-input" 
            className="btn btn-outline" 
            style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: '8px' }}
          >
            <FileText size={18} />
            {selectedFile ? selectedFile.name : 'Choose Document'}
          </label>

          {selectedFile && (
            <button 
              type="submit" 
              className="btn btn-primary" 
              disabled={isUploading}
              style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}
            >
              <CheckCircle2 size={18} />
              {isUploading ? 'Extracting Data...' : 'Start Analysis'}
            </button>
          )}
        </div>
      </form>

      {isUploading && (
        <p style={{ fontSize: '0.8rem', color: 'var(--color-primary)', marginTop: '14px', fontWeight: '500' }}>
          Parsing document parameters for eligibility matching...
        </p>
      )}
    </div>
  );
}