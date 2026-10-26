import { Lock } from "lucide-react";

import { usePageTitle } from "../components/layout/PageHeader";
import { ButtonLink } from "../components/ui/Button";
import { EmptyState } from "../components/ui/States";

export function ForbiddenPage() {
  usePageTitle("Access denied");
  return (
    <EmptyState
      icon={<Lock size={28} />}
      title="You do not have access to this page"
      message="Your role does not include this module. Ask the DrukSmart administrator if you need access."
      action={<ButtonLink to="/">Go to overview</ButtonLink>}
    />
  );
}
