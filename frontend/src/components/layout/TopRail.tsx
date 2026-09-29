import React from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { useStore } from '../../store/useStore';
import { HelpCircle, Sliders } from 'lucide-react';

export const TopRail: React.FC = () => {
  const location = useLocation();
  const {
    lots,
    activeLot,
    setActiveLot,
    inspector,
    setShortcutModalOpen,
    setDevModalOpen,
  } = useStore();

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
      {/* Brand & Wordmark */}
      <div className="flex items-center gap-6">
        <div className="flex items-baseline gap-1.5">
          <span className="font-mono font-bold tracking-wider text-sm text-white">
            PARIKSHAK
          </span>
          <span className="font-mono text-[10px] text-[#8A949B]">v0.9</span>
        </div>

        {/* Navigation Tabs */}
        <nav className="flex items-center space-x-1 h-[36px]">
          {navLinks.map(link => {
            const isActive =
              location.pathname === link.to ||
              (link.to === '/drift' && location.pathname === '/');
            return (
              <NavLink
                key={link.to}
                to={link.to}
                className={`h-[36px] px-3 flex items-center font-sans text-xs transition-colors relative ${
                  isActive
                    ? 'text-white font-semibold'
                    : 'text-[#9DA6AD] hover:text-white'
                }`}
              >
                {link.label}
                {isActive && (
                  <span className="absolute bottom-0 left-2 right-2 h-[2px] bg-white" />
                )}
              </NavLink>
            );
          })}
        </nav>
      </div>

      {/* Right Controls: Lot selector, Test condition, Inspector & Tools */}
      <div className="flex items-center gap-3 font-mono text-xs">
        {/* Lot Selector */}
        {lots.length > 0 && activeLot && (
          <div className="flex items-center gap-1.5 bg-[#252E34] px-2 py-0.5 border border-[#3A444C]">
            <span className="text-[#8A949B] text-[11px]">LOT:</span>
            <select
              value={activeLot.id}
              onChange={e => setActiveLot(e.target.value)}
              className="bg-transparent text-white font-mono text-xs focus:outline-none cursor-pointer"
            >
              {lots.map(l => (
                <option key={l.id} value={l.id} className="bg-toprail text-white">
                  {l.lotNumber}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Test condition from store */}
        {activeLot && (
          <div className="bg-[#252E34] px-2 py-0.5 border border-[#3A444C] text-[#C9CED2] text-[11px]">
            {activeLot.testCondition}
          </div>
        )}

        {/* User Chip from store */}
        <div className="bg-[#252E34] px-2 py-0.5 border border-[#3A444C] text-white text-[11px] flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-accept inline-block" />
          <span>QA Inspector: {inspector}</span>
        </div>

        {/* Shortcuts Help Button */}
        <button
          onClick={() => setShortcutModalOpen(true)}
          title="Keyboard shortcuts (?)"
          className="p-1 text-[#8A949B] hover:text-white hover:bg-[#252E34] transition-colors"
        >
          <HelpCircle size={14} />
        </button>

        {/* Dev Tools Drawer Toggle */}
        <button
          onClick={() => setDevModalOpen(true)}
          title="Demo Lot Generator Settings"
          className="p-1 text-[#8A949B] hover:text-white hover:bg-[#252E34] transition-colors flex items-center gap-1 text-[11px]"
        >
          <Sliders size={13} />
          <span className="font-sans">Dev</span>
        </button>
      </div>
    </header>
  );
};
