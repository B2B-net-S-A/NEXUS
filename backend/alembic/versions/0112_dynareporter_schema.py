"""DynaReporter B.0 — schema dla 57 tabel z prefixem dr_.

Revision ID: 0111_dynareporter_schema
Revises: 0110_dynareporter_user_extensions
Create Date: 2026-05-18 12:30:00.000000

Phase B.0 PR #2 z planu migracji DynaReportera
(.claude/plans/zaplanuj-migracje-pelna-nie-parallel-acorn.md).

Kopiuje 57 tabel z systemu DynaReporter (Render / Coolify standalone) do
nexus postgres, z prefixem ``dr_``. Wykluczona tabela ``users`` —
DynaReporter user data jest migrowany przez ETL (PR #4) z remapingiem
``user_id`` na ``nexus.users.id``.

Wszystkie FK ``REFERENCES public.users(id)`` w dr_* tabelach wskazują na
nexus.users (post-migracja po ETL). Tabele puste — dane wgrywane przez
PR #4 ETL.

Schema wygenerowany skryptem
``/tmp/dynareporter-migration/generate_dr_schema_migration.py`` z dumpa
``render-dump-clean.sql``.

Forward-only — drop tabel zniszczyłby historię migracji.
"""

from alembic import op


revision = "0111_dynareporter_schema"
down_revision = "0110_dynareporter_user_extensions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE public.dr_about_calendar (
            id integer NOT NULL,
            title character varying(255) NOT NULL,
            description text,
            event_date date NOT NULL,
            event_end_date date,
            event_type character varying(50) NOT NULL,
            is_all_day boolean DEFAULT true,
            created_by integer,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_about_calendar_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_about_calendar_id_seq OWNED BY public.dr_about_calendar.id;
        CREATE TABLE public.dr_about_career_paths (
            id integer NOT NULL,
            department character varying(100) NOT NULL,
            name character varying(255) NOT NULL,
            path_data jsonb NOT NULL,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_about_career_paths_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_about_career_paths_id_seq OWNED BY public.dr_about_career_paths.id;
        CREATE TABLE public.dr_about_clients_partners (
            id integer NOT NULL,
            name character varying(255) NOT NULL,
            logo_path character varying(500),
            description text,
            case_study text,
            website_url character varying(500),
            is_partner boolean DEFAULT false,
            sort_order integer DEFAULT 0,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_about_clients_partners_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_about_clients_partners_id_seq OWNED BY public.dr_about_clients_partners.id;
        CREATE TABLE public.dr_about_contacts (
            id integer NOT NULL,
            topic character varying(255) NOT NULL,
            description text,
            user_id integer,
            contact_name character varying(255),
            email character varying(255),
            phone character varying(50),
            sort_order integer DEFAULT 0,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_about_contacts_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_about_contacts_id_seq OWNED BY public.dr_about_contacts.id;
        CREATE TABLE public.dr_about_faq (
            id integer NOT NULL,
            question text NOT NULL,
            answer text,
            category character varying(100) NOT NULL,
            is_approved boolean DEFAULT false,
            proposed_by integer,
            approved_by integer,
            sort_order integer DEFAULT 0,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_about_faq_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_about_faq_id_seq OWNED BY public.dr_about_faq.id;
        CREATE TABLE public.dr_about_feedback (
            id integer NOT NULL,
            user_id integer NOT NULL,
            title character varying(255) NOT NULL,
            content text NOT NULL,
            category character varying(100),
            status character varying(50) DEFAULT 'new'::character varying,
            admin_notes text,
            resolved_by integer,
            resolved_at timestamp without time zone,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_about_feedback_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_about_feedback_id_seq OWNED BY public.dr_about_feedback.id;
        CREATE TABLE public.dr_about_glossary (
            id integer NOT NULL,
            term character varying(255) NOT NULL,
            definition text NOT NULL,
            category character varying(100),
            sort_order integer DEFAULT 0,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_about_glossary_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_about_glossary_id_seq OWNED BY public.dr_about_glossary.id;
        CREATE TABLE public.dr_about_links (
            id integer NOT NULL,
            name character varying(255) NOT NULL,
            description text,
            url character varying(500) NOT NULL,
            category character varying(100),
            sort_order integer DEFAULT 0,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_about_links_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_about_links_id_seq OWNED BY public.dr_about_links.id;
        CREATE TABLE public.dr_about_org_chart (
            id integer NOT NULL,
            parent_id integer,
            user_id integer,
            name character varying(255) NOT NULL,
            email character varying(255),
            phone character varying(50),
            "position" character varying(255),
            department character varying(100),
            is_absent boolean DEFAULT false,
            absence_reason character varying(100),
            absence_until date,
            sort_order integer DEFAULT 0,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_about_org_chart_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_about_org_chart_id_seq OWNED BY public.dr_about_org_chart.id;
        CREATE TABLE public.dr_about_positions (
            id integer NOT NULL,
            name character varying(255) NOT NULL,
            description text,
            requirements text,
            kpi text,
            career_path text,
            department character varying(100),
            sort_order integer DEFAULT 0,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_about_positions_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_about_positions_id_seq OWNED BY public.dr_about_positions.id;
        CREATE TABLE public.dr_about_procedures (
            id integer NOT NULL,
            name character varying(255) NOT NULL,
            description text,
            flowchart_data jsonb,
            category character varying(100),
            sort_order integer DEFAULT 0,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_about_procedures_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_about_procedures_id_seq OWNED BY public.dr_about_procedures.id;
        CREATE TABLE public.dr_about_templates (
            id integer NOT NULL,
            name character varying(255) NOT NULL,
            description text,
            category character varying(100) NOT NULL,
            file_path character varying(500) NOT NULL,
            file_name character varying(255) NOT NULL,
            file_size integer,
            mime_type character varying(100),
            version character varying(20) DEFAULT '1.0'::character varying,
            uploaded_by integer,
            sort_order integer DEFAULT 0,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_about_templates_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_about_templates_id_seq OWNED BY public.dr_about_templates.id;
        CREATE TABLE public.dr_about_training (
            id integer NOT NULL,
            name character varying(255) NOT NULL,
            description text,
            file_path character varying(500),
            file_name character varying(255),
            file_type character varying(50),
            external_url character varying(500),
            mime_type character varying(100),
            file_size integer,
            category character varying(100),
            department character varying(100),
            uploaded_by integer,
            sort_order integer DEFAULT 0,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_about_training_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_about_training_id_seq OWNED BY public.dr_about_training.id;
        CREATE TABLE public.dr_about_values (
            id integer NOT NULL,
            content text NOT NULL,
            updated_by integer,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_about_values_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_about_values_id_seq OWNED BY public.dr_about_values.id;
        CREATE TABLE public.dr_alerts (
            id integer NOT NULL,
            user_id integer NOT NULL,
            alert_type character varying(50) NOT NULL,
            message text NOT NULL,
            is_sent boolean DEFAULT false,
            sent_at timestamp without time zone,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_alerts_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_alerts_id_seq OWNED BY public.dr_alerts.id;
        CREATE TABLE public.dr_api_key_audit_log (
            id integer NOT NULL,
            api_key_id integer,
            method character varying(10) NOT NULL,
            path character varying(500) NOT NULL,
            status_code integer,
            ip_address character varying(45),
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_api_key_audit_log_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_api_key_audit_log_id_seq OWNED BY public.dr_api_key_audit_log.id;
        CREATE TABLE public.dr_api_keys (
            id integer NOT NULL,
            name character varying(100) NOT NULL,
            key_hash character varying(255) NOT NULL,
            key_prefix character varying(12) NOT NULL,
            scopes text[] DEFAULT '{*}'::text[],
            is_active boolean DEFAULT true,
            created_by integer,
            last_used_at timestamp without time zone,
            expires_at timestamp without time zone,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_api_keys_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_api_keys_id_seq OWNED BY public.dr_api_keys.id;
        CREATE TABLE public.dr_applied_migrations (
            name character varying(255) NOT NULL,
            applied_at timestamp with time zone DEFAULT now()
        );
        CREATE TABLE public.dr_board_monthly_report (
            id integer NOT NULL,
            report_month date NOT NULL,
            revenue numeric(12,2) DEFAULT 0,
            consultant_costs numeric(12,2) DEFAULT 0,
            other_costs numeric(12,2) DEFAULT 0,
            active_consultants integer DEFAULT 0,
            departures integer DEFAULT 0,
            placements integer DEFAULT 0,
            avg_margin_per_hour numeric(10,2) DEFAULT 0,
            hit_ratio numeric(5,2) DEFAULT 0,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_board_monthly_report_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_board_monthly_report_id_seq OWNED BY public.dr_board_monthly_report.id;
        CREATE TABLE public.dr_board_placement_clients (
            id integer NOT NULL,
            report_month date NOT NULL,
            client_name character varying(255) NOT NULL,
            placement_count integer DEFAULT 0,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_board_placement_clients_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_board_placement_clients_id_seq OWNED BY public.dr_board_placement_clients.id;
        CREATE TABLE public.dr_client_mrr (
            id integer NOT NULL,
            client_id integer NOT NULL,
            report_month date NOT NULL,
            consultants_count integer DEFAULT 0,
            mrr numeric(12,2) DEFAULT 0,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_client_mrr_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_client_mrr_id_seq OWNED BY public.dr_client_mrr.id;
        CREATE TABLE public.dr_clients (
            id integer NOT NULL,
            name character varying(255) NOT NULL,
            is_active boolean DEFAULT true,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_clients_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_clients_id_seq OWNED BY public.dr_clients.id;
        CREATE TABLE public.dr_competence_categories (
            id integer NOT NULL,
            name character varying(255) NOT NULL,
            color character varying(50) DEFAULT 'blue'::character varying,
            sort_order integer DEFAULT 0,
            is_active boolean DEFAULT true,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_competence_categories_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_competence_categories_id_seq OWNED BY public.dr_competence_categories.id;
        CREATE TABLE public.dr_competition_notifications (
            id integer NOT NULL,
            user_id integer NOT NULL,
            notification_type character varying(50) NOT NULL,
            competition_type character varying(50) NOT NULL,
            title character varying(255) NOT NULL,
            message text NOT NULL,
            is_read boolean DEFAULT false,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT competition_notifications_notification_type_check CHECK (((notification_type)::text = ANY ((ARRAY['position_change'::character varying, 'new_leader'::character varying, 'time_warning'::character varying, 'winner'::character varying, 'new_competition'::character varying])::text[])))
        );
        CREATE SEQUENCE public.dr_competition_notifications_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_competition_notifications_id_seq OWNED BY public.dr_competition_notifications.id;
        CREATE TABLE public.dr_competition_winners (
            id integer NOT NULL,
            competition_type character varying(50) NOT NULL,
            period character varying(20) NOT NULL,
            user_id integer NOT NULL,
            rank integer NOT NULL,
            points integer DEFAULT 0,
            metric_value integer DEFAULT 0,
            prize character varying(100),
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT competition_winners_competition_type_check CHECK (((competition_type)::text = ANY ((ARRAY['quarterly'::character varying, 'monthly_recommendations'::character varying, 'monthly_placements'::character varying])::text[]))),
            CONSTRAINT competition_winners_rank_check CHECK ((rank = ANY (ARRAY[1, 2, 3])))
        );
        CREATE SEQUENCE public.dr_competition_winners_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_competition_winners_id_seq OWNED BY public.dr_competition_winners.id;
        CREATE TABLE public.dr_consultant_group_assignments (
            consultant_id integer NOT NULL,
            group_id integer NOT NULL,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE public.dr_consultant_rate_history (
            id integer NOT NULL,
            consultant_id integer NOT NULL,
            project_id integer NOT NULL,
            cost_rate numeric(10,2) NOT NULL,
            revenue_rate numeric(10,2) NOT NULL,
            valid_from date NOT NULL,
            valid_to date,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_consultant_rate_history_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_consultant_rate_history_id_seq OWNED BY public.dr_consultant_rate_history.id;
        CREATE TABLE public.dr_consultants (
            id integer NOT NULL,
            name character varying(255) NOT NULL,
            is_active boolean DEFAULT true,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            default_cost_rate numeric(10,2) DEFAULT 0,
            default_revenue_rate numeric(10,2) DEFAULT 0,
            deactivated_at timestamp without time zone
        );
        CREATE SEQUENCE public.dr_consultants_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_consultants_id_seq OWNED BY public.dr_consultants.id;
        CREATE TABLE public.dr_data_audit_log (
            id integer NOT NULL,
            table_name character varying(100) NOT NULL,
            record_ids integer[] DEFAULT '{}'::integer[] NOT NULL,
            action character varying(20) NOT NULL,
            details jsonb,
            records_count integer DEFAULT 0,
            performed_by integer,
            performed_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT data_audit_log_action_check CHECK (((action)::text = ANY ((ARRAY['DELETE'::character varying, 'BULK_DELETE'::character varying, 'SOFT_DELETE'::character varying])::text[])))
        );
        CREATE SEQUENCE public.dr_data_audit_log_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_data_audit_log_id_seq OWNED BY public.dr_data_audit_log.id;
        CREATE TABLE public.dr_delivery_lead_client_assignments (
            id integer NOT NULL,
            delivery_lead_user_id integer NOT NULL,
            client_id integer NOT NULL,
            is_head boolean DEFAULT false,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_delivery_lead_client_assignments_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_delivery_lead_client_assignments_id_seq OWNED BY public.dr_delivery_lead_client_assignments.id;
        CREATE TABLE public.dr_finances (
            id integer NOT NULL,
            report_month date NOT NULL,
            total_revenue numeric(12,2) DEFAULT 0,
            total_costs numeric(12,2) DEFAULT 0,
            cv_database_count integer DEFAULT 0,
            consultants_churn integer DEFAULT 0,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            department character varying(50),
            CONSTRAINT finances_department_check CHECK (((department)::text = ANY ((ARRAY['body_leasing'::character varying, 'sales'::character varying, 'przetargi'::character varying, 'overhead'::character varying])::text[])))
        );
        CREATE SEQUENCE public.dr_finances_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_finances_id_seq OWNED BY public.dr_finances.id;
        CREATE TABLE public.dr_group_monthly_costs (
            id integer NOT NULL,
            group_id integer,
            month date NOT NULL,
            bl_cost numeric(10,2) DEFAULT 0,
            pm_cost numeric(10,2) DEFAULT 0,
            other_costs numeric(10,2) DEFAULT 0,
            description text,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_group_monthly_costs_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_group_monthly_costs_id_seq OWNED BY public.dr_group_monthly_costs.id;
        CREATE TABLE public.dr_kpi_body_leasing (
            id integer NOT NULL,
            user_id integer NOT NULL,
            report_date date NOT NULL,
            week_number integer NOT NULL,
            verifications integer DEFAULT 0,
            recommendations integer DEFAULT 0,
            interviews integer DEFAULT 0,
            placements integer DEFAULT 0,
            requests integer DEFAULT 0,
            days_worked integer DEFAULT 5,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            is_draft boolean DEFAULT false,
            linkedin_cv_added integer DEFAULT 0,
            linkedin_messages_sent integer DEFAULT 0,
            linkedin_responses_received integer DEFAULT 0
        );
        CREATE SEQUENCE public.dr_kpi_body_leasing_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_kpi_body_leasing_id_seq OWNED BY public.dr_kpi_body_leasing.id;
        CREATE TABLE public.dr_kpi_delivery_lead (
            id integer NOT NULL,
            user_id integer NOT NULL,
            report_month date NOT NULL,
            requests integer DEFAULT 0,
            placements integer DEFAULT 0,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            vacancies integer DEFAULT 0,
            open_requests integer DEFAULT 0,
            open_vacancies integer DEFAULT 0
        );
        CREATE SEQUENCE public.dr_kpi_delivery_lead_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_kpi_delivery_lead_id_seq OWNED BY public.dr_kpi_delivery_lead.id;
        CREATE TABLE public.dr_kpi_sales (
            id integer NOT NULL,
            user_id integer NOT NULL,
            report_date date NOT NULL,
            week_number integer NOT NULL,
            leads integer DEFAULT 0,
            offers_sent integer DEFAULT 0,
            offers_won integer DEFAULT 0,
            offers_lost integer DEFAULT 0,
            days_worked integer DEFAULT 5,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_kpi_sales_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_kpi_sales_id_seq OWNED BY public.dr_kpi_sales.id;
        CREATE TABLE public.dr_monthly_mrr_data (
            id integer NOT NULL,
            project_id integer,
            consultant_id integer,
            month date NOT NULL,
            rbh_cost numeric(10,2) DEFAULT 0,
            rbh_sales numeric(10,2) DEFAULT 0,
            cost_rate numeric(10,2) DEFAULT 0,
            revenue_rate numeric(10,2) DEFAULT 0,
            consultant_revenue numeric(12,2) DEFAULT 0,
            consultant_cost numeric(12,2) DEFAULT 0,
            net_value numeric(12,2) DEFAULT 0,
            operating_costs numeric(12,2) DEFAULT 0,
            pm_cost numeric(12,2) DEFAULT 0,
            bl_service_cost numeric(12,2) DEFAULT 0,
            margin numeric(12,2) DEFAULT 0,
            ap_hod numeric(12,2) DEFAULT 0,
            lp_bdm numeric(12,2) DEFAULT 0,
            ap_bdm numeric(12,2) DEFAULT 0,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            is_draft boolean DEFAULT false,
            ap_hod_enabled boolean DEFAULT true,
            lp_bdm_enabled boolean DEFAULT true,
            ap_bdm_enabled boolean DEFAULT true,
            head_bonus numeric(12,2) DEFAULT 0,
            bdm_bonus numeric(12,2) DEFAULT 0
        );
        CREATE SEQUENCE public.dr_monthly_mrr_data_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_monthly_mrr_data_id_seq OWNED BY public.dr_monthly_mrr_data.id;
        CREATE TABLE public.dr_mrr_import_history (
            id integer NOT NULL,
            import_type character varying(50) NOT NULL,
            filename character varying(255),
            month date,
            rows_imported integer DEFAULT 0,
            imported_by integer,
            status character varying(20) DEFAULT 'success'::character varying,
            error_message text,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT mrr_import_history_import_type_check CHECK (((import_type)::text = ANY ((ARRAY['mrr_monthly'::character varying, 'sales_weekly'::character varying])::text[]))),
            CONSTRAINT mrr_import_history_status_check CHECK (((status)::text = ANY ((ARRAY['success'::character varying, 'failed'::character varying, 'partial'::character varying])::text[])))
        );
        CREATE SEQUENCE public.dr_mrr_import_history_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_mrr_import_history_id_seq OWNED BY public.dr_mrr_import_history.id;
        CREATE TABLE public.dr_placement_details (
            id integer NOT NULL,
            user_id integer NOT NULL,
            client_id integer NOT NULL,
            placement_date date NOT NULL,
            week_number integer,
            notes text,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_placement_details_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_placement_details_id_seq OWNED BY public.dr_placement_details.id;
        CREATE TABLE public.dr_project_cost_groups (
            id integer NOT NULL,
            project_id integer,
            name character varying(100) NOT NULL,
            is_active boolean DEFAULT true,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_project_cost_groups_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_project_cost_groups_id_seq OWNED BY public.dr_project_cost_groups.id;
        CREATE TABLE public.dr_project_monthly_costs (
            id integer NOT NULL,
            project_id integer,
            month date NOT NULL,
            bl_cost numeric(10,2) DEFAULT 0,
            pm_cost numeric(10,2) DEFAULT 0,
            other_costs numeric(10,2) DEFAULT 0,
            description text,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_project_monthly_costs_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_project_monthly_costs_id_seq OWNED BY public.dr_project_monthly_costs.id;
        CREATE TABLE public.dr_project_other_cost_items (
            id integer NOT NULL,
            project_id integer,
            month date NOT NULL,
            name character varying(100) NOT NULL,
            amount numeric(10,2) DEFAULT 0 NOT NULL,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_project_other_cost_items_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_project_other_cost_items_id_seq OWNED BY public.dr_project_other_cost_items.id;
        CREATE TABLE public.dr_przetargi_allocations (
            id integer NOT NULL,
            project_id integer NOT NULL,
            consultant_id integer NOT NULL,
            month date NOT NULL,
            hours numeric(8,2) DEFAULT 0,
            cost_rate numeric(10,2) DEFAULT 0,
            revenue_rate numeric(10,2) DEFAULT 0,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_przetargi_allocations_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_przetargi_allocations_id_seq OWNED BY public.dr_przetargi_allocations.id;
        CREATE TABLE public.dr_przetargi_consultants (
            id integer NOT NULL,
            name character varying(255) NOT NULL,
            default_cost_rate numeric(10,2) DEFAULT 0,
            default_revenue_rate numeric(10,2) DEFAULT 0,
            is_active boolean DEFAULT true,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_przetargi_consultants_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_przetargi_consultants_id_seq OWNED BY public.dr_przetargi_consultants.id;
        CREATE TABLE public.dr_przetargi_mrr (
            id integer CONSTRAINT przetargi_mrr_id_not_null1 NOT NULL,
            project_id integer NOT NULL,
            consultant_id integer CONSTRAINT przetargi_mrr_consultant_id_not_null1 NOT NULL,
            month date CONSTRAINT przetargi_mrr_month_not_null1 NOT NULL,
            hours numeric(8,2) DEFAULT 0,
            cost_rate numeric(10,2) DEFAULT 0,
            revenue_rate numeric(10,2) DEFAULT 0,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE public.dr_przetargi_mrr_backup (
            id integer CONSTRAINT przetargi_mrr_id_not_null NOT NULL,
            consultant_id integer CONSTRAINT przetargi_mrr_consultant_id_not_null NOT NULL,
            month date CONSTRAINT przetargi_mrr_month_not_null NOT NULL,
            hours numeric(8,2) DEFAULT 0,
            cost_rate numeric(10,2) DEFAULT 0,
            revenue_rate numeric(10,2) DEFAULT 0,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            client_id integer
        );
        CREATE SEQUENCE public.dr_przetargi_mrr_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_przetargi_mrr_id_seq OWNED BY public.dr_przetargi_mrr_backup.id;
        CREATE SEQUENCE public.przetargi_mrr_id_seq1
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.przetargi_mrr_id_seq1 OWNED BY public.dr_przetargi_mrr.id;
        CREATE TABLE public.dr_przetargi_project_costs (
            id integer NOT NULL,
            project_id integer NOT NULL,
            month date NOT NULL,
            description character varying(255) NOT NULL,
            value numeric(10,2) DEFAULT 0,
            category character varying(50) DEFAULT 'other'::character varying NOT NULL,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT przetargi_project_costs_category_check CHECK (((category)::text = ANY ((ARRAY['infrastructure'::character varying, 'licenses'::character varying, 'travel'::character varying, 'other'::character varying])::text[])))
        );
        CREATE SEQUENCE public.dr_przetargi_project_costs_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_przetargi_project_costs_id_seq OWNED BY public.dr_przetargi_project_costs.id;
        CREATE TABLE public.dr_przetargi_projects (
            id integer NOT NULL,
            name character varying(255) NOT NULL,
            is_active boolean DEFAULT true,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            client_id integer,
            updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_przetargi_projects_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_przetargi_projects_id_seq OWNED BY public.dr_przetargi_projects.id;
        CREATE TABLE public.dr_sales_leads (
            id integer NOT NULL,
            user_id integer NOT NULL,
            week_start date NOT NULL,
            company_name character varying(255) NOT NULL,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_sales_leads_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_sales_leads_id_seq OWNED BY public.dr_sales_leads.id;
        CREATE TABLE public.dr_sales_offers (
            id integer NOT NULL,
            user_id integer NOT NULL,
            week_start date NOT NULL,
            company_name character varying(255) NOT NULL,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_sales_offers_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_sales_offers_id_seq OWNED BY public.dr_sales_offers.id;
        CREATE TABLE public.dr_sales_people (
            id integer NOT NULL,
            name character varying(255) NOT NULL,
            role character varying(50) NOT NULL,
            is_hod boolean DEFAULT false,
            is_active boolean DEFAULT true,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            deactivated_at timestamp without time zone,
            CONSTRAINT sales_people_role_check CHECK (((role)::text = ANY ((ARRAY['hod'::character varying, 'bdm'::character varying])::text[])))
        );
        CREATE SEQUENCE public.dr_sales_people_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_sales_people_id_seq OWNED BY public.dr_sales_people.id;
        CREATE TABLE public.dr_sales_projects (
            id integer NOT NULL,
            name character varying(255) NOT NULL,
            bdm_id integer,
            is_active boolean DEFAULT true,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_sales_projects_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_sales_projects_id_seq OWNED BY public.dr_sales_projects.id;
        CREATE TABLE public.dr_sourcer_category_assignments (
            id integer NOT NULL,
            user_id integer NOT NULL,
            category_id integer NOT NULL,
            priority integer NOT NULL,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT sourcer_category_assignments_priority_check CHECK ((priority = ANY (ARRAY[1, 2])))
        );
        CREATE SEQUENCE public.dr_sourcer_category_assignments_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_sourcer_category_assignments_id_seq OWNED BY public.dr_sourcer_category_assignments.id;
        CREATE TABLE public.dr_system_config (
            id integer NOT NULL,
            key character varying(100) NOT NULL,
            value jsonb NOT NULL,
            description text,
            updated_by integer,
            updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_system_config_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_system_config_id_seq OWNED BY public.dr_system_config.id;
        CREATE TABLE public.dr_tac_delivery_lead_assignments (
            id integer NOT NULL,
            tac_user_id integer NOT NULL,
            delivery_lead_user_id integer NOT NULL,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_tac_delivery_lead_assignments_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_tac_delivery_lead_assignments_id_seq OWNED BY public.dr_tac_delivery_lead_assignments.id;
        CREATE TABLE public.dr_tac_linkedin_farming (
            id integer NOT NULL,
            tac_user_id integer NOT NULL,
            category_id integer NOT NULL,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
        );
        CREATE SEQUENCE public.dr_tac_linkedin_farming_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_tac_linkedin_farming_id_seq OWNED BY public.dr_tac_linkedin_farming.id;
        CREATE TABLE public.dr_upload_history (
            id integer NOT NULL,
            uploaded_by integer NOT NULL,
            file_type character varying(50) NOT NULL,
            file_name character varying(255) NOT NULL,
            records_count integer DEFAULT 0,
            status character varying(20) DEFAULT 'success'::character varying,
            error_message text,
            created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT upload_history_file_type_check CHECK (((file_type)::text = ANY ((ARRAY['body_leasing'::character varying, 'sales'::character varying, 'finances'::character varying, 'mrr_monthly'::character varying, 'sales_weekly'::character varying])::text[]))),
            CONSTRAINT upload_history_status_check CHECK (((status)::text = ANY ((ARRAY['success'::character varying, 'failed'::character varying, 'partial'::character varying])::text[])))
        );
        CREATE SEQUENCE public.dr_upload_history_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_upload_history_id_seq OWNED BY public.dr_upload_history.id;
        CREATE SEQUENCE public.dr_weekly_sales_activity_id_seq
            AS integer
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        ALTER SEQUENCE public.dr_weekly_sales_activity_id_seq OWNED BY public.dr_weekly_sales_activity.id;
        ALTER TABLE ONLY public.dr_about_calendar ALTER COLUMN id SET DEFAULT nextval('public.dr_about_calendar_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_about_career_paths ALTER COLUMN id SET DEFAULT nextval('public.dr_about_career_paths_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_about_clients_partners ALTER COLUMN id SET DEFAULT nextval('public.dr_about_clients_partners_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_about_contacts ALTER COLUMN id SET DEFAULT nextval('public.dr_about_contacts_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_about_faq ALTER COLUMN id SET DEFAULT nextval('public.dr_about_faq_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_about_feedback ALTER COLUMN id SET DEFAULT nextval('public.dr_about_feedback_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_about_glossary ALTER COLUMN id SET DEFAULT nextval('public.dr_about_glossary_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_about_links ALTER COLUMN id SET DEFAULT nextval('public.dr_about_links_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_about_org_chart ALTER COLUMN id SET DEFAULT nextval('public.dr_about_org_chart_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_about_positions ALTER COLUMN id SET DEFAULT nextval('public.dr_about_positions_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_about_procedures ALTER COLUMN id SET DEFAULT nextval('public.dr_about_procedures_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_about_templates ALTER COLUMN id SET DEFAULT nextval('public.dr_about_templates_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_about_training ALTER COLUMN id SET DEFAULT nextval('public.dr_about_training_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_about_values ALTER COLUMN id SET DEFAULT nextval('public.dr_about_values_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_alerts ALTER COLUMN id SET DEFAULT nextval('public.dr_alerts_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_api_key_audit_log ALTER COLUMN id SET DEFAULT nextval('public.dr_api_key_audit_log_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_api_keys ALTER COLUMN id SET DEFAULT nextval('public.dr_api_keys_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_board_monthly_report ALTER COLUMN id SET DEFAULT nextval('public.dr_board_monthly_report_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_board_placement_clients ALTER COLUMN id SET DEFAULT nextval('public.dr_board_placement_clients_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_client_mrr ALTER COLUMN id SET DEFAULT nextval('public.dr_client_mrr_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_clients ALTER COLUMN id SET DEFAULT nextval('public.dr_clients_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_competence_categories ALTER COLUMN id SET DEFAULT nextval('public.dr_competence_categories_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_competition_notifications ALTER COLUMN id SET DEFAULT nextval('public.dr_competition_notifications_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_competition_winners ALTER COLUMN id SET DEFAULT nextval('public.dr_competition_winners_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_consultant_rate_history ALTER COLUMN id SET DEFAULT nextval('public.dr_consultant_rate_history_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_consultants ALTER COLUMN id SET DEFAULT nextval('public.dr_consultants_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_data_audit_log ALTER COLUMN id SET DEFAULT nextval('public.dr_data_audit_log_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_delivery_lead_client_assignments ALTER COLUMN id SET DEFAULT nextval('public.dr_delivery_lead_client_assignments_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_finances ALTER COLUMN id SET DEFAULT nextval('public.dr_finances_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_group_monthly_costs ALTER COLUMN id SET DEFAULT nextval('public.dr_group_monthly_costs_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_kpi_body_leasing ALTER COLUMN id SET DEFAULT nextval('public.dr_kpi_body_leasing_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_kpi_delivery_lead ALTER COLUMN id SET DEFAULT nextval('public.dr_kpi_delivery_lead_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_kpi_sales ALTER COLUMN id SET DEFAULT nextval('public.dr_kpi_sales_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_monthly_mrr_data ALTER COLUMN id SET DEFAULT nextval('public.dr_monthly_mrr_data_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_mrr_import_history ALTER COLUMN id SET DEFAULT nextval('public.dr_mrr_import_history_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_placement_details ALTER COLUMN id SET DEFAULT nextval('public.dr_placement_details_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_project_cost_groups ALTER COLUMN id SET DEFAULT nextval('public.dr_project_cost_groups_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_project_monthly_costs ALTER COLUMN id SET DEFAULT nextval('public.dr_project_monthly_costs_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_project_other_cost_items ALTER COLUMN id SET DEFAULT nextval('public.dr_project_other_cost_items_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_przetargi_allocations ALTER COLUMN id SET DEFAULT nextval('public.dr_przetargi_allocations_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_przetargi_consultants ALTER COLUMN id SET DEFAULT nextval('public.dr_przetargi_consultants_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_przetargi_mrr ALTER COLUMN id SET DEFAULT nextval('public.przetargi_mrr_id_seq1'::regclass);
        ALTER TABLE ONLY public.dr_przetargi_mrr_backup ALTER COLUMN id SET DEFAULT nextval('public.dr_przetargi_mrr_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_przetargi_project_costs ALTER COLUMN id SET DEFAULT nextval('public.dr_przetargi_project_costs_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_przetargi_projects ALTER COLUMN id SET DEFAULT nextval('public.dr_przetargi_projects_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_sales_leads ALTER COLUMN id SET DEFAULT nextval('public.dr_sales_leads_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_sales_offers ALTER COLUMN id SET DEFAULT nextval('public.dr_sales_offers_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_sales_people ALTER COLUMN id SET DEFAULT nextval('public.dr_sales_people_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_sales_projects ALTER COLUMN id SET DEFAULT nextval('public.dr_sales_projects_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_sourcer_category_assignments ALTER COLUMN id SET DEFAULT nextval('public.dr_sourcer_category_assignments_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_system_config ALTER COLUMN id SET DEFAULT nextval('public.dr_system_config_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_tac_delivery_lead_assignments ALTER COLUMN id SET DEFAULT nextval('public.dr_tac_delivery_lead_assignments_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_tac_linkedin_farming ALTER COLUMN id SET DEFAULT nextval('public.dr_tac_linkedin_farming_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_upload_history ALTER COLUMN id SET DEFAULT nextval('public.dr_upload_history_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_weekly_sales_activity ALTER COLUMN id SET DEFAULT nextval('public.dr_weekly_sales_activity_id_seq'::regclass);
        ALTER TABLE ONLY public.dr_about_calendar
            ADD CONSTRAINT dr_about_calendar_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_about_career_paths
            ADD CONSTRAINT dr_about_career_paths_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_about_clients_partners
            ADD CONSTRAINT dr_about_clients_partners_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_about_contacts
            ADD CONSTRAINT dr_about_contacts_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_about_faq
            ADD CONSTRAINT dr_about_faq_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_about_feedback
            ADD CONSTRAINT dr_about_feedback_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_about_glossary
            ADD CONSTRAINT dr_about_glossary_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_about_glossary
            ADD CONSTRAINT dr_about_glossary_term_key UNIQUE (term);
        ALTER TABLE ONLY public.dr_about_links
            ADD CONSTRAINT dr_about_links_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_about_org_chart
            ADD CONSTRAINT dr_about_org_chart_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_about_positions
            ADD CONSTRAINT dr_about_positions_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_about_procedures
            ADD CONSTRAINT dr_about_procedures_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_about_templates
            ADD CONSTRAINT dr_about_templates_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_about_training
            ADD CONSTRAINT dr_about_training_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_about_values
            ADD CONSTRAINT dr_about_values_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_alerts
            ADD CONSTRAINT dr_alerts_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_api_key_audit_log
            ADD CONSTRAINT dr_api_key_audit_log_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_api_keys
            ADD CONSTRAINT dr_api_keys_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_applied_migrations
            ADD CONSTRAINT dr_applied_migrations_pkey PRIMARY KEY (name);
        ALTER TABLE ONLY public.dr_board_monthly_report
            ADD CONSTRAINT dr_board_monthly_report_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_board_monthly_report
            ADD CONSTRAINT dr_board_monthly_report_report_month_key UNIQUE (report_month);
        ALTER TABLE ONLY public.dr_board_placement_clients
            ADD CONSTRAINT dr_board_placement_clients_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_board_placement_clients
            ADD CONSTRAINT dr_board_placement_clients_report_month_client_name_key UNIQUE (report_month, client_name);
        ALTER TABLE ONLY public.dr_client_mrr
            ADD CONSTRAINT dr_client_mrr_client_id_report_month_key UNIQUE (client_id, report_month);
        ALTER TABLE ONLY public.dr_client_mrr
            ADD CONSTRAINT dr_client_mrr_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_clients
            ADD CONSTRAINT dr_clients_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_competence_categories
            ADD CONSTRAINT dr_competence_categories_name_key UNIQUE (name);
        ALTER TABLE ONLY public.dr_competence_categories
            ADD CONSTRAINT dr_competence_categories_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_competition_notifications
            ADD CONSTRAINT dr_competition_notifications_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_competition_winners
            ADD CONSTRAINT dr_competition_winners_competition_type_period_rank_key UNIQUE (competition_type, period, rank);
        ALTER TABLE ONLY public.dr_competition_winners
            ADD CONSTRAINT dr_competition_winners_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_consultant_group_assignments
            ADD CONSTRAINT dr_consultant_group_assignments_pkey PRIMARY KEY (consultant_id, group_id);
        ALTER TABLE ONLY public.dr_consultant_rate_history
            ADD CONSTRAINT dr_consultant_rate_history_consultant_id_project_id_valid_from_key UNIQUE (consultant_id, project_id, valid_from);
        ALTER TABLE ONLY public.dr_consultant_rate_history
            ADD CONSTRAINT dr_consultant_rate_history_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_consultants
            ADD CONSTRAINT dr_consultants_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_data_audit_log
            ADD CONSTRAINT dr_data_audit_log_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_delivery_lead_client_assignments
            ADD CONSTRAINT delivery_lead_client_assignme_delivery_lead_user_id_client__key UNIQUE (delivery_lead_user_id, client_id);
        ALTER TABLE ONLY public.dr_delivery_lead_client_assignments
            ADD CONSTRAINT dr_delivery_lead_client_assignments_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_finances
            ADD CONSTRAINT dr_finances_month_dept_unique UNIQUE (report_month, department);
        ALTER TABLE ONLY public.dr_finances
            ADD CONSTRAINT dr_finances_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_group_monthly_costs
            ADD CONSTRAINT dr_group_monthly_costs_group_id_month_key UNIQUE (group_id, month);
        ALTER TABLE ONLY public.dr_group_monthly_costs
            ADD CONSTRAINT dr_group_monthly_costs_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_kpi_body_leasing
            ADD CONSTRAINT dr_kpi_body_leasing_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_kpi_delivery_lead
            ADD CONSTRAINT dr_kpi_delivery_lead_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_kpi_delivery_lead
            ADD CONSTRAINT dr_kpi_delivery_lead_user_id_report_month_key UNIQUE (user_id, report_month);
        ALTER TABLE ONLY public.dr_kpi_sales
            ADD CONSTRAINT dr_kpi_sales_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_kpi_sales
            ADD CONSTRAINT dr_kpi_sales_user_id_report_date_key UNIQUE (user_id, report_date);
        ALTER TABLE ONLY public.dr_monthly_mrr_data
            ADD CONSTRAINT dr_monthly_mrr_data_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_mrr_import_history
            ADD CONSTRAINT dr_mrr_import_history_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_placement_details
            ADD CONSTRAINT dr_placement_details_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_project_cost_groups
            ADD CONSTRAINT dr_project_cost_groups_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_project_monthly_costs
            ADD CONSTRAINT dr_project_monthly_costs_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_project_monthly_costs
            ADD CONSTRAINT dr_project_monthly_costs_project_id_month_key UNIQUE (project_id, month);
        ALTER TABLE ONLY public.dr_project_other_cost_items
            ADD CONSTRAINT dr_project_other_cost_items_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_przetargi_allocations
            ADD CONSTRAINT dr_przetargi_allocations_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_przetargi_allocations
            ADD CONSTRAINT dr_przetargi_allocations_project_consultant_month_key UNIQUE (project_id, consultant_id, month);
        ALTER TABLE ONLY public.dr_przetargi_consultants
            ADD CONSTRAINT dr_przetargi_consultants_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_przetargi_mrr_backup
            ADD CONSTRAINT dr_przetargi_mrr_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_przetargi_mrr
            ADD CONSTRAINT dr_przetargi_mrr_pkey1 PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_przetargi_mrr_backup
            ADD CONSTRAINT dr_przetargi_mrr_unique_entry UNIQUE (client_id, consultant_id, month);
        ALTER TABLE ONLY public.dr_przetargi_project_costs
            ADD CONSTRAINT dr_przetargi_project_costs_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_przetargi_projects
            ADD CONSTRAINT dr_przetargi_projects_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_sales_leads
            ADD CONSTRAINT dr_sales_leads_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_sales_offers
            ADD CONSTRAINT dr_sales_offers_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_sales_people
            ADD CONSTRAINT dr_sales_people_name_unique UNIQUE (name);
        ALTER TABLE ONLY public.dr_sales_people
            ADD CONSTRAINT dr_sales_people_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_sales_projects
            ADD CONSTRAINT dr_sales_projects_name_key UNIQUE (name);
        ALTER TABLE ONLY public.dr_sales_projects
            ADD CONSTRAINT dr_sales_projects_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_sourcer_category_assignments
            ADD CONSTRAINT dr_sourcer_category_assignments_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_sourcer_category_assignments
            ADD CONSTRAINT dr_sourcer_category_assignments_unique_user_category_priority UNIQUE (category_id, user_id, priority);
        ALTER TABLE ONLY public.dr_system_config
            ADD CONSTRAINT dr_system_config_key_key UNIQUE (key);
        ALTER TABLE ONLY public.dr_system_config
            ADD CONSTRAINT dr_system_config_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_tac_delivery_lead_assignments
            ADD CONSTRAINT dr_tac_delivery_lead_assignments_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_tac_delivery_lead_assignments
            ADD CONSTRAINT dr_tac_delivery_lead_assignments_tac_user_id_key UNIQUE (tac_user_id);
        ALTER TABLE ONLY public.dr_tac_linkedin_farming
            ADD CONSTRAINT dr_tac_linkedin_farming_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_tac_linkedin_farming
            ADD CONSTRAINT dr_tac_linkedin_farming_tac_user_id_category_id_key UNIQUE (tac_user_id, category_id);
        ALTER TABLE ONLY public.dr_upload_history
            ADD CONSTRAINT dr_upload_history_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.users
            ADD CONSTRAINT users_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_weekly_sales_activity
            ADD CONSTRAINT dr_weekly_sales_activity_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY public.dr_weekly_sales_activity
            ADD CONSTRAINT dr_weekly_sales_activity_week_start_key UNIQUE (week_start);
        CREATE INDEX idx_dr_about_calendar_date ON public.dr_about_calendar USING btree (event_date);
        CREATE INDEX idx_dr_about_faq_approved ON public.dr_about_faq USING btree (is_approved);
        CREATE INDEX idx_dr_about_faq_category ON public.dr_about_faq USING btree (category);
        CREATE INDEX idx_dr_about_feedback_status ON public.dr_about_feedback USING btree (status);
        CREATE INDEX idx_dr_about_feedback_user ON public.dr_about_feedback USING btree (user_id);
        CREATE INDEX idx_dr_about_glossary_term ON public.dr_about_glossary USING btree (term);
        CREATE INDEX idx_dr_about_org_chart_parent ON public.dr_about_org_chart USING btree (parent_id);
        CREATE INDEX idx_dr_about_org_chart_user ON public.dr_about_org_chart USING btree (user_id);
        CREATE INDEX idx_dr_about_procedures_category ON public.dr_about_procedures USING btree (category);
        CREATE INDEX idx_dr_about_templates_category ON public.dr_about_templates USING btree (category);
        CREATE INDEX idx_dr_about_training_category ON public.dr_about_training USING btree (category);
        CREATE INDEX idx_api_key_audit_created ON public.dr_api_key_audit_log USING btree (created_at);
        CREATE INDEX idx_api_key_audit_key_id ON public.dr_api_key_audit_log USING btree (api_key_id);
        CREATE INDEX idx_dr_api_keys_prefix ON public.dr_api_keys USING btree (key_prefix);
        CREATE INDEX idx_audit_log_date ON public.dr_data_audit_log USING btree (performed_at);
        CREATE INDEX idx_audit_log_table ON public.dr_data_audit_log USING btree (table_name);
        CREATE INDEX idx_audit_log_user ON public.dr_data_audit_log USING btree (performed_by);
        CREATE INDEX idx_dr_board_monthly_report_month ON public.dr_board_monthly_report USING btree (report_month);
        CREATE INDEX idx_dr_board_placement_clients_month ON public.dr_board_placement_clients USING btree (report_month);
        CREATE INDEX idx_dr_client_mrr_month ON public.dr_client_mrr USING btree (report_month);
        CREATE INDEX idx_dr_competition_notifications_unread ON public.dr_competition_notifications USING btree (user_id, is_read) WHERE (is_read = false);
        CREATE INDEX idx_dr_competition_notifications_user ON public.dr_competition_notifications USING btree (user_id);
        CREATE INDEX idx_dr_competition_winners_period ON public.dr_competition_winners USING btree (period);
        CREATE INDEX idx_dr_competition_winners_type ON public.dr_competition_winners USING btree (competition_type);
        CREATE INDEX idx_dr_consultant_group_assignments_consultant ON public.dr_consultant_group_assignments USING btree (consultant_id);
        CREATE INDEX idx_dr_consultant_group_assignments_group ON public.dr_consultant_group_assignments USING btree (group_id);
        CREATE INDEX idx_dr_consultant_rate_history_consultant ON public.dr_consultant_rate_history USING btree (consultant_id);
        CREATE INDEX idx_dr_consultant_rate_history_project ON public.dr_consultant_rate_history USING btree (project_id);
        CREATE INDEX idx_dr_consultants_active ON public.dr_consultants USING btree (is_active);
        CREATE INDEX idx_dr_consultants_name ON public.dr_consultants USING btree (name);
        CREATE INDEX idx_dl_client_client ON public.dr_delivery_lead_client_assignments USING btree (client_id);
        CREATE INDEX idx_dl_client_dl ON public.dr_delivery_lead_client_assignments USING btree (delivery_lead_user_id);
        CREATE INDEX idx_dr_finances_department ON public.dr_finances USING btree (department);
        CREATE INDEX idx_dr_finances_month ON public.dr_finances USING btree (report_month);
        CREATE INDEX idx_dr_finances_month_department ON public.dr_finances USING btree (report_month, department);
        CREATE INDEX idx_dr_group_monthly_costs_group_month ON public.dr_group_monthly_costs USING btree (group_id, month);
        CREATE INDEX idx_dr_kpi_body_leasing_date ON public.dr_kpi_body_leasing USING btree (report_date);
        CREATE INDEX idx_dr_kpi_body_leasing_is_draft ON public.dr_kpi_body_leasing USING btree (is_draft);
        CREATE INDEX idx_dr_kpi_body_leasing_user ON public.dr_kpi_body_leasing USING btree (user_id);
        CREATE INDEX idx_dr_kpi_delivery_lead_month ON public.dr_kpi_delivery_lead USING btree (report_month);
        CREATE INDEX idx_dr_kpi_delivery_lead_user ON public.dr_kpi_delivery_lead USING btree (user_id);
        CREATE INDEX idx_dr_kpi_sales_date ON public.dr_kpi_sales USING btree (report_date);
        CREATE INDEX idx_dr_kpi_sales_user ON public.dr_kpi_sales USING btree (user_id);
        CREATE INDEX idx_dr_monthly_mrr_data_consultant ON public.dr_monthly_mrr_data USING btree (consultant_id);
        CREATE INDEX idx_dr_monthly_mrr_data_is_draft ON public.dr_monthly_mrr_data USING btree (is_draft);
        CREATE INDEX idx_dr_monthly_mrr_data_month ON public.dr_monthly_mrr_data USING btree (month);
        CREATE INDEX idx_dr_monthly_mrr_data_project ON public.dr_monthly_mrr_data USING btree (project_id);
        CREATE INDEX idx_dr_monthly_mrr_data_project_month ON public.dr_monthly_mrr_data USING btree (project_id, month);
        CREATE INDEX idx_dr_monthly_mrr_data_project_month_consultant ON public.dr_monthly_mrr_data USING btree (project_id, month, consultant_id);
        CREATE INDEX idx_dr_placement_details_client ON public.dr_placement_details USING btree (client_id);
        CREATE INDEX idx_dr_placement_details_date ON public.dr_placement_details USING btree (placement_date);
        CREATE INDEX idx_dr_placement_details_user ON public.dr_placement_details USING btree (user_id);
        CREATE INDEX idx_dr_placement_details_week ON public.dr_placement_details USING btree (week_number);
        CREATE INDEX idx_dr_project_cost_groups_project ON public.dr_project_cost_groups USING btree (project_id);
        CREATE INDEX idx_dr_project_monthly_costs_project_month ON public.dr_project_monthly_costs USING btree (project_id, month);
        CREATE INDEX idx_dr_project_other_cost_items_project_month ON public.dr_project_other_cost_items USING btree (project_id, month);
        CREATE INDEX idx_dr_przetargi_allocations_consultant ON public.dr_przetargi_allocations USING btree (consultant_id);
        CREATE INDEX idx_dr_przetargi_allocations_month ON public.dr_przetargi_allocations USING btree (month);
        CREATE INDEX idx_dr_przetargi_allocations_project ON public.dr_przetargi_allocations USING btree (project_id);
        CREATE INDEX idx_dr_przetargi_mrr_client ON public.dr_przetargi_mrr_backup USING btree (client_id);
        CREATE INDEX idx_dr_przetargi_mrr_consultant ON public.dr_przetargi_mrr_backup USING btree (consultant_id);
        CREATE INDEX idx_dr_przetargi_mrr_month ON public.dr_przetargi_mrr_backup USING btree (month);
        CREATE INDEX idx_dr_przetargi_mrr_project ON public.dr_przetargi_mrr USING btree (project_id);
        CREATE INDEX idx_dr_przetargi_project_costs_month ON public.dr_przetargi_project_costs USING btree (month);
        CREATE INDEX idx_dr_przetargi_project_costs_project ON public.dr_przetargi_project_costs USING btree (project_id);
        CREATE INDEX idx_dr_przetargi_projects_active ON public.dr_przetargi_projects USING btree (is_active);
        CREATE INDEX idx_dr_przetargi_projects_client ON public.dr_przetargi_projects USING btree (client_id);
        CREATE INDEX idx_dr_sales_leads_user_week ON public.dr_sales_leads USING btree (user_id, week_start);
        CREATE INDEX idx_dr_sales_leads_week ON public.dr_sales_leads USING btree (week_start);
        CREATE INDEX idx_dr_sales_offers_user_week ON public.dr_sales_offers USING btree (user_id, week_start);
        CREATE INDEX idx_dr_sales_offers_week ON public.dr_sales_offers USING btree (week_start);
        CREATE INDEX idx_dr_sales_projects_bdm ON public.dr_sales_projects USING btree (bdm_id);
        CREATE INDEX idx_sourcer_category_category ON public.dr_sourcer_category_assignments USING btree (category_id);
        CREATE INDEX idx_sourcer_category_user ON public.dr_sourcer_category_assignments USING btree (user_id);
        CREATE INDEX idx_tac_dl_dl ON public.dr_tac_delivery_lead_assignments USING btree (delivery_lead_user_id);
        CREATE INDEX idx_tac_dl_tac ON public.dr_tac_delivery_lead_assignments USING btree (tac_user_id);
        CREATE INDEX idx_tac_linkedin_category ON public.dr_tac_linkedin_farming USING btree (category_id);
        CREATE INDEX idx_tac_linkedin_tac ON public.dr_tac_linkedin_farming USING btree (tac_user_id);
        CREATE INDEX idx_dr_weekly_sales_activity_week ON public.dr_weekly_sales_activity USING btree (week_start);
        CREATE UNIQUE INDEX dr_kpi_body_leasing_unique_non_draft ON public.dr_kpi_body_leasing USING btree (user_id, report_date) WHERE (is_draft = false);
        ALTER TABLE ONLY public.dr_about_calendar
            ADD CONSTRAINT dr_about_calendar_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);
        ALTER TABLE ONLY public.dr_about_contacts
            ADD CONSTRAINT dr_about_contacts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;
        ALTER TABLE ONLY public.dr_about_faq
            ADD CONSTRAINT dr_about_faq_approved_by_fkey FOREIGN KEY (approved_by) REFERENCES public.users(id);
        ALTER TABLE ONLY public.dr_about_faq
            ADD CONSTRAINT dr_about_faq_proposed_by_fkey FOREIGN KEY (proposed_by) REFERENCES public.users(id);
        ALTER TABLE ONLY public.dr_about_feedback
            ADD CONSTRAINT dr_about_feedback_resolved_by_fkey FOREIGN KEY (resolved_by) REFERENCES public.users(id);
        ALTER TABLE ONLY public.dr_about_feedback
            ADD CONSTRAINT dr_about_feedback_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
        ALTER TABLE ONLY public.dr_about_org_chart
            ADD CONSTRAINT dr_about_org_chart_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.dr_about_org_chart(id) ON DELETE SET NULL;
        ALTER TABLE ONLY public.dr_about_org_chart
            ADD CONSTRAINT dr_about_org_chart_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;
        ALTER TABLE ONLY public.dr_about_templates
            ADD CONSTRAINT dr_about_templates_uploaded_by_fkey FOREIGN KEY (uploaded_by) REFERENCES public.users(id);
        ALTER TABLE ONLY public.dr_about_training
            ADD CONSTRAINT dr_about_training_uploaded_by_fkey FOREIGN KEY (uploaded_by) REFERENCES public.users(id);
        ALTER TABLE ONLY public.dr_about_values
            ADD CONSTRAINT dr_about_values_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id);
        ALTER TABLE ONLY public.dr_alerts
            ADD CONSTRAINT dr_alerts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
        ALTER TABLE ONLY public.dr_api_key_audit_log
            ADD CONSTRAINT dr_api_key_audit_log_api_key_id_fkey FOREIGN KEY (api_key_id) REFERENCES public.dr_api_keys(id) ON DELETE CASCADE;
        ALTER TABLE ONLY public.dr_api_keys
            ADD CONSTRAINT dr_api_keys_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);
        ALTER TABLE ONLY public.dr_client_mrr
            ADD CONSTRAINT dr_client_mrr_client_id_fkey FOREIGN KEY (client_id) REFERENCES public.dr_clients(id);
        ALTER TABLE ONLY public.dr_competition_notifications
            ADD CONSTRAINT dr_competition_notifications_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
        ALTER TABLE ONLY public.dr_competition_winners
            ADD CONSTRAINT dr_competition_winners_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
        ALTER TABLE ONLY public.dr_consultant_group_assignments
            ADD CONSTRAINT dr_consultant_group_assignments_consultant_id_fkey FOREIGN KEY (consultant_id) REFERENCES public.dr_consultants(id) ON DELETE CASCADE;
        ALTER TABLE ONLY public.dr_consultant_group_assignments
            ADD CONSTRAINT dr_consultant_group_assignments_group_id_fkey FOREIGN KEY (group_id) REFERENCES public.dr_project_cost_groups(id) ON DELETE CASCADE;
        ALTER TABLE ONLY public.dr_consultant_rate_history
            ADD CONSTRAINT dr_consultant_rate_history_consultant_id_fkey FOREIGN KEY (consultant_id) REFERENCES public.dr_consultants(id);
        ALTER TABLE ONLY public.dr_consultant_rate_history
            ADD CONSTRAINT dr_consultant_rate_history_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.dr_sales_projects(id);
        ALTER TABLE ONLY public.dr_data_audit_log
            ADD CONSTRAINT dr_data_audit_log_performed_by_fkey FOREIGN KEY (performed_by) REFERENCES public.users(id);
        ALTER TABLE ONLY public.dr_delivery_lead_client_assignments
            ADD CONSTRAINT dr_delivery_lead_client_assignments_client_id_fkey FOREIGN KEY (client_id) REFERENCES public.dr_clients(id) ON DELETE CASCADE;
        ALTER TABLE ONLY public.dr_delivery_lead_client_assignments
            ADD CONSTRAINT dr_delivery_lead_client_assignments_delivery_lead_user_id_fkey FOREIGN KEY (delivery_lead_user_id) REFERENCES public.users(id) ON DELETE CASCADE;
        ALTER TABLE ONLY public.dr_group_monthly_costs
            ADD CONSTRAINT dr_group_monthly_costs_group_id_fkey FOREIGN KEY (group_id) REFERENCES public.dr_project_cost_groups(id) ON DELETE CASCADE;
        ALTER TABLE ONLY public.dr_kpi_body_leasing
            ADD CONSTRAINT dr_kpi_body_leasing_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
        ALTER TABLE ONLY public.dr_kpi_delivery_lead
            ADD CONSTRAINT dr_kpi_delivery_lead_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
        ALTER TABLE ONLY public.dr_kpi_sales
            ADD CONSTRAINT dr_kpi_sales_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
        ALTER TABLE ONLY public.dr_monthly_mrr_data
            ADD CONSTRAINT dr_monthly_mrr_data_consultant_id_fkey FOREIGN KEY (consultant_id) REFERENCES public.dr_consultants(id) ON DELETE SET NULL;
        ALTER TABLE ONLY public.dr_monthly_mrr_data
            ADD CONSTRAINT dr_monthly_mrr_data_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.dr_sales_projects(id) ON DELETE SET NULL;
        ALTER TABLE ONLY public.dr_mrr_import_history
            ADD CONSTRAINT dr_mrr_import_history_imported_by_fkey FOREIGN KEY (imported_by) REFERENCES public.users(id);
        ALTER TABLE ONLY public.dr_placement_details
            ADD CONSTRAINT dr_placement_details_client_id_fkey FOREIGN KEY (client_id) REFERENCES public.dr_clients(id) ON DELETE CASCADE;
        ALTER TABLE ONLY public.dr_placement_details
            ADD CONSTRAINT dr_placement_details_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;
        ALTER TABLE ONLY public.dr_project_cost_groups
            ADD CONSTRAINT dr_project_cost_groups_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.dr_sales_projects(id) ON DELETE CASCADE;
        ALTER TABLE ONLY public.dr_project_monthly_costs
            ADD CONSTRAINT dr_project_monthly_costs_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.dr_sales_projects(id) ON DELETE CASCADE;
        ALTER TABLE ONLY public.dr_project_other_cost_items
            ADD CONSTRAINT dr_project_other_cost_items_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.dr_sales_projects(id) ON DELETE CASCADE;
        ALTER TABLE ONLY public.dr_przetargi_allocations
            ADD CONSTRAINT dr_przetargi_allocations_consultant_id_fkey FOREIGN KEY (consultant_id) REFERENCES public.dr_consultants(id);
        ALTER TABLE ONLY public.dr_przetargi_allocations
            ADD CONSTRAINT dr_przetargi_allocations_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.dr_przetargi_projects(id) ON DELETE CASCADE;
        ALTER TABLE ONLY public.dr_przetargi_mrr_backup
            ADD CONSTRAINT dr_przetargi_mrr_client_id_fkey FOREIGN KEY (client_id) REFERENCES public.dr_clients(id);
        ALTER TABLE ONLY public.dr_przetargi_mrr_backup
            ADD CONSTRAINT dr_przetargi_mrr_consultant_id_fkey FOREIGN KEY (consultant_id) REFERENCES public.dr_consultants(id);
        ALTER TABLE ONLY public.dr_przetargi_mrr
            ADD CONSTRAINT dr_przetargi_mrr_consultant_id_fkey1 FOREIGN KEY (consultant_id) REFERENCES public.dr_przetargi_consultants(id);
        ALTER TABLE ONLY public.dr_przetargi_mrr
            ADD CONSTRAINT dr_przetargi_mrr_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.dr_przetargi_projects(id);
        ALTER TABLE ONLY public.dr_przetargi_project_costs
            ADD CONSTRAINT dr_przetargi_project_costs_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.dr_przetargi_projects(id) ON DELETE CASCADE;
        ALTER TABLE ONLY public.dr_przetargi_projects
            ADD CONSTRAINT dr_przetargi_projects_client_id_fkey FOREIGN KEY (client_id) REFERENCES public.dr_clients(id);
        ALTER TABLE ONLY public.dr_sales_leads
            ADD CONSTRAINT dr_sales_leads_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
        ALTER TABLE ONLY public.dr_sales_offers
            ADD CONSTRAINT dr_sales_offers_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
        ALTER TABLE ONLY public.dr_sales_projects
            ADD CONSTRAINT dr_sales_projects_bdm_id_fkey FOREIGN KEY (bdm_id) REFERENCES public.users(id);
        ALTER TABLE ONLY public.dr_sourcer_category_assignments
            ADD CONSTRAINT dr_sourcer_category_assignments_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.dr_competence_categories(id) ON DELETE CASCADE;
        ALTER TABLE ONLY public.dr_sourcer_category_assignments
            ADD CONSTRAINT dr_sourcer_category_assignments_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;
        ALTER TABLE ONLY public.dr_system_config
            ADD CONSTRAINT dr_system_config_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id);
        ALTER TABLE ONLY public.dr_tac_delivery_lead_assignments
            ADD CONSTRAINT dr_tac_delivery_lead_assignments_delivery_lead_user_id_fkey FOREIGN KEY (delivery_lead_user_id) REFERENCES public.users(id) ON DELETE CASCADE;
        ALTER TABLE ONLY public.dr_tac_delivery_lead_assignments
            ADD CONSTRAINT dr_tac_delivery_lead_assignments_tac_user_id_fkey FOREIGN KEY (tac_user_id) REFERENCES public.users(id) ON DELETE CASCADE;
        ALTER TABLE ONLY public.dr_tac_linkedin_farming
            ADD CONSTRAINT dr_tac_linkedin_farming_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.dr_competence_categories(id) ON DELETE CASCADE;
        ALTER TABLE ONLY public.dr_tac_linkedin_farming
            ADD CONSTRAINT dr_tac_linkedin_farming_tac_user_id_fkey FOREIGN KEY (tac_user_id) REFERENCES public.users(id) ON DELETE CASCADE;
        ALTER TABLE ONLY public.dr_upload_history
            ADD CONSTRAINT dr_upload_history_uploaded_by_fkey FOREIGN KEY (uploaded_by) REFERENCES public.users(id);
        ALTER TABLE ONLY public.users
            ADD CONSTRAINT users_manager_id_fkey FOREIGN KEY (manager_id) REFERENCES public.users(id);
""")


def downgrade() -> None:
    raise NotImplementedError(
        "Forward-only: dropping 57 dr_* tables would destroy DynaReporter "
        "migration history. To roll back, point reports.dynaminds.pl back "
        "to Coolify standalone (which is still live during Faza B)."
    )

