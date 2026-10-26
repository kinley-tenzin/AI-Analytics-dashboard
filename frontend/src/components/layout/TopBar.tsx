import { LogOut, Menu } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";

import type { UserScope } from "../../api/types";
import { roleLabel } from "../../auth/access";
import { useSession } from "../../auth/session";
import { BrandMark } from "./BrandMark";

interface TopBarProps {
  user: UserScope;
  menuOpen: boolean;
  onMenu: () => void;
}

function initials(username: string): string {
  const parts = username.replace(/[^a-zA-Z0-9]+/g, " ").trim().split(" ");
  const letters = parts.length > 1 ? parts[0]![0]! + parts[parts.length - 1]![0]! : username.slice(0, 2);
  return letters.toUpperCase();
}

export function TopBar({ user, menuOpen, onMenu }: TopBarProps) {
  const { signOut } = useSession();
  const navigate = useNavigate();
  const [signingOut, setSigningOut] = useState(false);

  async function onSignOut() {
    setSigningOut(true);
    await signOut().catch(() => undefined); // the app forgets the user even if the call fails
    navigate("/login", { replace: true });
  }

  return (
    <header className="topbar">
      <button
        type="button"
        className="icon-btn topbar__menu"
        onClick={onMenu}
        aria-label="Open menu"
        aria-expanded={menuOpen}
        aria-controls="app-sidebar"
      >
        <Menu size={22} aria-hidden="true" />
      </button>
      <span className="topbar__brand">
        <BrandMark />
      </span>
      <div className="topbar__spacer" />
      <div className="user-chip" aria-label={`Signed in as ${user.username}`}>
        <span className="user-chip__avatar" aria-hidden="true">
          {initials(user.username)}
        </span>
        <span className="user-chip__text">
          <span className="user-chip__name">{user.username}</span>
          <span className="user-chip__role">
            {roleLabel(user)}
            {user.branch_restricted ? " · branch-restricted" : ""}
          </span>
        </span>
      </div>
      <button
        type="button"
        className="btn btn--ghost btn--sm topbar__signout"
        onClick={onSignOut}
        disabled={signingOut}
        aria-label="Sign out"
      >
        <LogOut size={16} aria-hidden="true" />
        <span>Sign out</span>
      </button>
    </header>
  );
}
