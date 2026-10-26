import { X } from "lucide-react";
import { NavLink } from "react-router";

import type { UserScope } from "../../api/types";
import { canAccess } from "../../auth/access";
import { NAV_SECTIONS } from "../../navigation";
import { BrandMark } from "./BrandMark";

interface SidebarProps {
  user: UserScope;
  open: boolean;
  onClose: () => void;
}

/** Role-aware navigation: shows only the pages the user's Django scope allows. */
export function Sidebar({ user, open, onClose }: SidebarProps) {
  const sections = NAV_SECTIONS.map((s) => ({
    ...s,
    items: s.items.filter((item) => canAccess(user, item.requires)),
  })).filter((s) => s.items.length > 0);

  return (
    <aside id="app-sidebar" className={["sidebar", open ? "sidebar--open" : ""].join(" ")}>
      <div className="sidebar__top">
        <BrandMark inverted />
        <button type="button" className="icon-btn sidebar__close" onClick={onClose} aria-label="Close menu">
          <X size={20} aria-hidden="true" />
        </button>
      </div>
      <nav className="sidebar__nav" aria-label="Main">
        {sections.map((section) => (
          <div className="sidebar__section" key={section.title}>
            <p className="sidebar__section-title">{section.title}</p>
            <ul>
              {section.items.map((item) => (
                <li key={item.key}>
                  <NavLink
                    to={item.path}
                    end={item.path === "/"}
                    className={({ isActive }) => ["nav-link", isActive ? "nav-link--active" : ""].join(" ")}
                    onClick={onClose}
                  >
                    <item.icon size={18} aria-hidden="true" />
                    <span>{item.label}</span>
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
        {sections.length === 0 && <p className="sidebar__empty">No analytics modules are assigned to you.</p>}
      </nav>
      <div className="sidebar__footer">
        <span className="sidebar__env">Prototype · local deployment</span>
      </div>
    </aside>
  );
}
