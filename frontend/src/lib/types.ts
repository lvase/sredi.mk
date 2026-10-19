export type ApiEnvelope<T> = { data: T };
export type ApiErrorEnvelope = {
  errors?: Record<string, unknown>;
  detail?: string;
  meta?: {
    retry_after_seconds?: number;
    current_version?: number;
    current_versions?: Record<string, number>;
  };
};

export type Municipality = {
  id: number;
  name: string;
  slug: string;
  configuration_status: "unverified" | "verified";
  public_accent_color: string;
  official_coat_of_arms_url: string | null;
  active_report_count: number;
  latest_public_notice: {
    id: number;
    title: string;
    summary: string;
    body: string;
    published_at: string;
  } | null;
};

export type Option = {
  id: number;
  name: string;
  municipality?: Municipality;
};

export type Choice = {
  value: string;
  label: string;
};

export type FormOptions = {
  municipality: Municipality;
  settlements: Option[];
  categories: Array<Option & { description?: string; default_department?: number | null }>;
};

export type PublicStats = {
  total: number;
  open: number;
  resolved: number;
  pending: number;
};

export type PublicIssueRow = {
  title: string;
  submitted_at: string;
  status: string;
  status_label: string;
};

export type PublicStatisticsPayload = {
  municipality: Municipality;
  applied_filters: {
    period: "30" | "90" | "365" | "all";
    settlement: string | null;
    category: string | null;
    status: string | null;
  };
  filter_options: {
    settlements: Option[];
    categories: Option[];
    statuses: Choice[];
  };
  stats: PublicStats;
  recent_reports: PublicIssueRow[];
  time_series: Array<{ bucket: string; total: number | null; suppressed: boolean }>;
  by_settlement: Array<{ label: string; total: number; suppressed: false }>;
  by_category: Array<{ label: string; total: number; suppressed: false }>;
  performance: {
    median_review_hours: number | null;
    median_resolution_hours: number | null;
    resolved_within_target_percent: number | null;
  };
  suppression: {
    minimum_group_size: number;
    suppressed_time_buckets: number;
    suppressed_category_groups: number;
    suppressed_settlement_groups: number;
    message: string;
  };
  definitions: Record<string, string>;
  last_updated: string | null;
};

export type PublicComment = {
  id: number;
  body: string;
  author: string;
  created_at: string;
};

export type PublicUpdate = {
  id: string;
  kind: "submitted" | "comment" | "status" | "note";
  title: string;
  body: string;
  status: string;
  status_label: string;
  created_at: string;
};

export type TrackedIssue = {
  id: number;
  tracking_code: string;
  title: string;
  settlement: string;
  category: string;
  status: string;
  status_label: string;
  submitted_at: string;
  updated_at: string;
  public_comments: PublicComment[];
  public_updates: PublicUpdate[];
};

export type UserSummary = {
  id: number;
  username: string;
  email: string;
  is_superuser: boolean;
  role?: string;
  municipality?: Municipality | null;
  department?: Option | null;
  two_factor_enabled: boolean;
  must_change_password: boolean;
};

export type SessionPayload = {
  isAuthenticated: boolean;
  user: UserSummary | null;
  csrfToken: string;
  pendingAuthentication?: boolean;
};

export type AuthNextStep = "authenticated" | "verify_2fa" | "enroll_superuser_2fa" | "change_password";

export type LoginResult = {
  authenticated: boolean;
  next_step: AuthNextStep;
  user?: UserSummary;
  csrfToken?: string;
  recovery_codes?: string[];
};

export type SecurityStatus = {
  two_factor_enabled: boolean;
  recovery_codes_remaining: number;
  trusted_devices: Array<{
    id: number;
    label: string;
    created_at: string;
    last_used_at: string | null;
    expires_at: string;
  }>;
};

export type StaffMetrics = {
  total: number;
  pending: number;
  open: number;
  my: number;
  overdue: number;
  unassigned: number;
  due_soon: number;
};

export type StaffIssue = {
  id: number;
  version: number;
  tracking_code: string;
  title: string;
  public_title: string;
  public_title_approved_at: string | null;
  municipality: string;
  municipality_id: number;
  settlement: string;
  category: string;
  location_text: string;
  status: string;
  status_label: string;
  priority: string;
  priority_label: string;
  assigned_department: string | null;
  assigned_department_id: number | null;
  assigned_to: string | null;
  assigned_to_id: number | null;
  submitted_at: string;
  updated_at: string;
  is_overdue: boolean;
  is_due_soon: boolean;
  quick_status_actions: Choice[];
};

export type StaffIssueDetail = StaffIssue & {
  description: string;
  citizen_name: string;
  citizen_email: string;
  citizen_phone: string;
  is_anonymous: boolean;
  suspicious_score: number;
  suspicious_reasons: Array<{ code: string; label: string; points: number }>;
  public_resolution_note: string;
  internal_note: string;
  attachments: Array<{
    id: number;
    url: string | null;
    uploaded_at: string;
    deletion_state: "active" | "deletion_pending" | "deleted" | "deletion_failed";
    deleted_at: string | null;
    deletion_reason: string;
  }>;
  comments: Array<PublicComment & { is_internal: boolean }>;
  status_events: Array<{
    id: number;
    from_status: string;
    to_status: string;
    to_status_label: string;
    changed_by: string | null;
    note: string;
    created_at: string;
  }>;
  audit_logs: Array<{
    id: number;
    action: string;
    actor: string | null;
    metadata: Record<string, unknown>;
    created_at: string;
  }>;
  permissions: {
    can_update: boolean;
    can_change_status: boolean;
    can_comment: boolean;
    can_moderate_public_title: boolean;
    can_manage_legal_hold: boolean;
  };
  public_title_approved_by: string | null;
  comments_count: number;
  status_events_count: number;
  audit_logs_count: number;
  comments_next_cursor: string | null;
  status_events_next_cursor: string | null;
  audit_logs_next_cursor: string | null;
  legal_hold_active: boolean;
  legal_hold_reason: string;
  legal_hold_set_at: string | null;
};

export type StaffChoices = {
  status_choices: Choice[];
  priority_choices: Choice[];
  role_choices: Choice[];
  municipalities: Municipality[];
  departments: Option[];
  assignees: UserSummary[];
  show_configuration_warning: boolean;
};

export type StaffIssuesPayload = {
  metrics: StaffMetrics;
  items: StaffIssue[];
  pagination: {
    page: number;
    page_size: number;
    total_items: number;
    total_pages: number;
    has_next: boolean;
    has_previous: boolean;
  };
};
