import React from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { useStore } from '../../store/useStore';
import { HelpCircle, Sliders } from 'lucide-react';

export const TopRail: React.FC = () => {
  const location = useLocation();
  const { lots, activeLot, setActiveLot, inspector, setInspector, setShortcutModalOpen, setDevModalOpen, mode, api } = useStore();

  const navLinks = [
    { to: '/lots', label: 'Lots' },
    { to: '/ingest', label: 'Ingest' },
    { to: '/outliers', label: 'Outliers' },
    { to: '/drift', label: 'Drift' },
    { to: '/components', label: 'Components' },
    { to: '/decisions', label: 'Decisions' },
    { to: '/model', label: 'Model' },
    { to: '/reports', label: 'Reports' },
  ];

  return (
    <header className="h-[36px] bg-toprail text-white flex items-center justify-between px-3 select-none text-xs border-b border-[#2C353D] shrink-0">
      <div className="flex items-center gap-6">
        <span className="font-mono font-bold tracking-wider text-sm text-white">PARIKSHAK</span>
        <nav className="flex items-center space-x-1 h-[36px]">
          {navLinks.map(link => {
            const isActive = location.pathname === link.to || (link.to === '/lots' && location.pathname === '/');
            return (
              <NavLink key={link.to} to={link.to}
                className={`h-[36px] px-3 flex items-center font-sans text-xs transition-colors relative ${isActive ? 'text-white font-semibold' : 'text-[#9DA6AD] hover:text-white'}`}>
                {link.label}
                {isActive && <span className="absolute bottom-0 left-2 right-2 h-[2px] bg-white" />}
              </NavLink>
            );
          })}
        </nav>
      </div>

      <div className="flex items-center gap-3 font-mono text-xs">
        <span title={api.description}
          className={`px-2 py-0.5 border text-[11px] ${mode === 'offline' ? 'border-review text-review' : 'border-[#3A444C] text-[#C9CED2]'}`}>
          {mode === 'offline' ? 'OFFLINE DEMO' : 'BACKEND'}
        </span>
        {lots.length > 0 && activeLot && (
          <div className="flex items-center gap-1.5 bg-[#252E34] px-2 py-0.5 border border-[#3A444C]">
            <span className="text-[#8A949B] text-[11px]">LOT:</span>
            <select value={activeLot.id} onChange={e => setActiveLot(e.target.value)}
              className="bg-transparent text-white font-mono text-xs focus:outline-none cursor-pointer">
              {lots.map(l => (
                <option key={l.id} value={l.id} className="bg-toprail text-white">
                  {l.lotNumber}{l.source === 'CSV_INGEST' ? ' (ingested)' : ''}
                </option>
              ))}
            </select>
          </div>
        )}
        <label className="bg-[#252E34] px-2 py-0.5 border border-[#3A444C] text-white text-[11px] flex items-center gap-1.5">
          <span className={`w-1.5 h-1.5 rounded-full inline-block ${inspector.trim().length >= 2 ? 'bg-accept' : 'bg-review'}`} />
          <span className="text-[#8A949B]">Inspector ID:</span>
          <input value={inspector} onChange={e => setInspector(e.target.value)} placeholder="set badge ID"
            className="bg-transparent w-[110px] text-white placeholder:text-[#8A949B] focus:outline-none" />
        </label>
        <button onClick={() => setShortcutModalOpen(true)} title="Keyboard shortcuts (?)"
          className="p-1 text-[#8A949B] hover:text-white hover:bg-[#252E34] transition-colors">
          <HelpCircle size={14} />
        </button>
        <button onClick={() => setDevModalOpen(true)} title="Data source and offline demo settings"
          className="p-1 text-[#8A949B] hover:text-white hover:bg-[#252E34] transition-colors flex items-center gap-1 text-[11px]">
          <Sliders size={13} />
          <span className="font-sans">Source</span>
        </button>
      </div>
    </header>
  );
};
