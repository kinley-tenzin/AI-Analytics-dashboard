import { SearchX } from "lucide-react";

import { usePageTitle } from "../components/layout/PageHeader";
import { ButtonLink } from "../components/ui/Button";
import { EmptyState } from "../components/ui/States";

export function NotFoundPage() {
  usePageTitle("Page not found");
  return (
    <EmptyState
      icon={<SearchX size={28} />}
      title="Page not found"
      message="The address does not match any page of DrukSmart Analytics."
      action={<ButtonLink to="/">Go to overview</ButtonLink>}
    />
  );
}
