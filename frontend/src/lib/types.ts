// Mirrors meditrack/schemas.py. Kept hand-written and small rather than
// generated, so the shape the client relies on is visible in one place.

export interface User {
  id: number;
  username: string;
  full_name: string;
  last_login_at: string | null;
}

export interface Meta {
  app_name: string;
  sexes: string[];
  appointment_statuses: string[];
  payment_statuses: string[];
  slot_minutes: number;
  max_attachment_bytes: number;
  allowed_attachment_types: Record<string, string>;
  storage_backend: string;
}

export interface Doctor {
  id: number;
  full_name: string;
  specialisation: string;
  phone: string | null;
  room: string | null;
  consultation_fee: string;
}

export interface Patient {
  id: number;
  mrn: string;
  full_name: string;
  date_of_birth: string;
  age: number;
  sex: string;
  phone: string;
  address: string | null;
  blood_group: string | null;
  allergies: string | null;
  created_at: string;
}

export interface PatientList {
  items: Patient[];
  total: number;
  page: number;
  page_size: number;
  has_next: boolean;
}

export interface PatientRef {
  id: number;
  full_name: string;
  mrn: string;
}

export interface DoctorRef {
  id: number;
  full_name: string;
  specialisation: string;
}

export interface Appointment {
  id: number;
  scheduled_at: string;
  reason: string | null;
  status: string;
  patient: PatientRef;
  doctor: DoctorRef;
  consultation_id: number | null;
}

export interface SessionNote {
  id: number;
  title: string;
  created_at: string;
  author_name: string;
  body: string | null;
  unavailable: boolean;
  attachment_filename: string | null;
  attachment_size_label: string | null;
  has_attachment: boolean;
}

export interface Consultation {
  id: number;
  visited_at: string;
  symptoms: string | null;
  diagnosis: string;
  prescription: string | null;
  notes: string | null;
  follow_up_on: string | null;
  fee: string;
  payment_status: string;
  patient: PatientRef;
  doctor: DoctorRef;
}

export interface ConsultationDetail extends Consultation {
  patient_allergies: string | null;
  session_notes: SessionNote[];
}

export interface Dashboard {
  today: string;
  stats: {
    patients: number;
    doctors: number;
    today_total: number;
    today_waiting: number;
    consultations: number;
    outstanding: string;
  };
  todays: Appointment[];
  upcoming: Appointment[];
  recent: {
    id: number;
    visited_at: string;
    patient_name: string;
    diagnosis: string;
  }[];
}
