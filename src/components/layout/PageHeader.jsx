
export default function PageHeader({ title, subtitle, action = null }) {
  return (
    <header className="page-header">
      <div className="page-header-copy">
        <h1 className="page-title">{title}</h1>
        {subtitle && <p className="page-subtitle">{subtitle}</p>}
      </div>
      {action && <div className="page-header-action">{action}</div>}
    </header>
  );
}