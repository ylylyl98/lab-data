import { Boxes, Database, FlaskConical } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link, NavLink } from 'react-router-dom';

const NAV = [
  { to: '/devices', label: 'Devices', icon: Database },
  { to: '/experiments', label: 'Experiments', icon: FlaskConical },
  { to: '/artifacts', label: 'Artifacts', icon: Boxes },
];

export function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="app">
      <header className="topbar">
        <Link className="brand" to="/">
          Lab Data Browser
        </Link>
        <nav className="nav">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
            >
              <Icon size={16} aria-hidden="true" />
              {label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="content">{children}</main>
    </div>
  );
}
