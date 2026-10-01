from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.utils import TIME_RE, MONTH_RE, DATE_RE

Role = Literal["admin", "employee"]
UserStatus = Literal["active", "inactive"]
LeaveType = Literal["casual", "sick", "earned", "unpaid"]
AttendanceStatus = Literal["present", "half_day", "absent", "leave", "holiday"]


def _check_time(v):
    if v in (None, ""):
        return None
    if not TIME_RE.match(v):
        raise ValueError("Time must be HH:MM (24-hour)")
    return v


def _check_date(v):
    if v in (None, ""):
        return None
    if not DATE_RE.match(v):
        raise ValueError("Date must be YYYY-MM-DD")
    date.fromisoformat(v)
    return v


def _blank_to_none(v):
    return None if isinstance(v, str) and not v.strip() else v


# ---------- Auth ----------
class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6, max_length=128)


class ProfileUpdateIn(BaseModel):
    phone: Optional[str] = Field(None, max_length=20)
    address: Optional[str] = Field(None, max_length=300)
    emergency_contact: Optional[str] = Field(None, max_length=100)


# ---------- Users ----------
class UserBase(BaseModel):
    phone: Optional[str] = Field(None, max_length=20)
    employee_code: Optional[str] = Field(None, max_length=20)
    department_id: Optional[str] = None
    designation: Optional[str] = Field(None, max_length=100)
    date_of_joining: Optional[str] = None
    date_of_birth: Optional[str] = None
    gender: Optional[str] = None
    address: Optional[str] = Field(None, max_length=300)
    emergency_contact: Optional[str] = Field(None, max_length=100)
    shift_start: Optional[str] = None
    shift_end: Optional[str] = None
    # Weekly off day (0 = Monday ... 6 = Sunday) and one extra off date; both are days off for this employee
    week_off_day: Optional[int] = Field(None, ge=0, le=6)
    week_off_date: Optional[str] = None
    bank_account: Optional[str] = Field(None, max_length=40)
    ifsc: Optional[str] = Field(None, max_length=20)
    pan: Optional[str] = Field(None, max_length=20)

    @field_validator("phone", "employee_code", "department_id", "designation", "gender",
                     "address", "emergency_contact", "bank_account", "ifsc", "pan", mode="before")
    @classmethod
    def blanks(cls, v):
        return _blank_to_none(v)

    @field_validator("date_of_joining", "date_of_birth", "week_off_date", mode="before")
    @classmethod
    def dates(cls, v):
        return _check_date(_blank_to_none(v))

    @field_validator("week_off_day", mode="before")
    @classmethod
    def week_off(cls, v):
        return _blank_to_none(v)

    @field_validator("shift_start", "shift_end", mode="before")
    @classmethod
    def times(cls, v):
        return _check_time(_blank_to_none(v))


class UserCreate(UserBase):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    salary: float = Field(0, ge=0)
    role: Role = "employee"
    status: UserStatus = "active"


class UserUpdate(UserBase):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=6, max_length=128)
    salary: Optional[float] = Field(None, ge=0)
    role: Optional[Role] = None
    status: Optional[UserStatus] = None

    @field_validator("password", mode="before")
    @classmethod
    def blank_pw(cls, v):
        return _blank_to_none(v)


# ---------- Departments / holidays / announcements ----------
class DepartmentIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: Optional[str] = Field(None, max_length=300)


class HolidayIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    date: str
    description: Optional[str] = Field(None, max_length=300)

    @field_validator("date")
    @classmethod
    def valid_date(cls, v):
        if not _check_date(v):
            raise ValueError("Date is required")
        return v


class AnnouncementIn(BaseModel):
    title: str = Field(min_length=2, max_length=150)
    body: str = Field(min_length=2, max_length=3000)
    priority: Literal["normal", "important"] = "normal"


# ---------- Leaves ----------
class LeaveIn(BaseModel):
    leave_type: LeaveType
    start_date: str
    end_date: str
    half_day: bool = False
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("start_date", "end_date")
    @classmethod
    def valid_dates(cls, v):
        if not _check_date(v):
            raise ValueError("Date is required")
        return v

    @model_validator(mode="after")
    def check_range(self):
        if self.end_date < self.start_date:
            raise ValueError("End date cannot be before start date")
        if self.half_day and self.start_date != self.end_date:
            raise ValueError("Half-day leave must be a single day")
        return self


class LeaveDecisionIn(BaseModel):
    status: Literal["approved", "rejected"]
    remarks: Optional[str] = Field(None, max_length=300)


# ---------- Attendance ----------
class AttendanceMarkIn(BaseModel):
    user_id: str
    date: str
    status: AttendanceStatus
    check_in_time: Optional[str] = None
    check_out_time: Optional[str] = None
    remarks: Optional[str] = Field(None, max_length=300)

    @field_validator("date")
    @classmethod
    def valid_date(cls, v):
        if not _check_date(v):
            raise ValueError("Date is required")
        return v

    @field_validator("check_in_time", "check_out_time", mode="before")
    @classmethod
    def times(cls, v):
        return _check_time(_blank_to_none(v))


# ---------- Payroll ----------
class PayrollGenerateIn(BaseModel):
    month: str

    @field_validator("month")
    @classmethod
    def valid_month(cls, v):
        if not MONTH_RE.match(v):
            raise ValueError("Month must be YYYY-MM")
        return v


class PayrollUpdateIn(BaseModel):
    bonus: Optional[float] = Field(None, ge=0)
    other_deductions: Optional[float] = Field(None, ge=0)
    status: Optional[Literal["draft", "paid"]] = None
    remarks: Optional[str] = Field(None, max_length=300)


# ---------- Company settings ----------
class LeaveQuota(BaseModel):
    casual: float = Field(12, ge=0)
    sick: float = Field(8, ge=0)
    earned: float = Field(15, ge=0)


class SettingsIn(BaseModel):
    company_name: str = Field("My Company", min_length=1, max_length=100)
    office_start: str = "09:30"
    office_end: str = "18:30"
    grace_minutes: int = Field(15, ge=0, le=180)
    half_day_hours: float = Field(4, ge=0, le=24)
    full_day_hours: float = Field(8, ge=0, le=24)
    working_days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])
    office_lat: Optional[float] = Field(None, ge=-90, le=90)
    office_lng: Optional[float] = Field(None, ge=-180, le=180)
    office_radius_m: int = Field(200, ge=10, le=100000)
    enforce_geofence: bool = False
    require_selfie: bool = True
    leave_quota: LeaveQuota = Field(default_factory=LeaveQuota)
    # Late arrivals on or after this date (YYYY-MM-DD) are cut from salary; None = every late arrival counts
    late_cut_start: Optional[str] = None

    @field_validator("late_cut_start", mode="before")
    @classmethod
    def cut_start(cls, v):
        if v in (None, ""):
            return None
        try:
            return date.fromisoformat(str(v)).isoformat()
        except ValueError:
            raise ValueError("Late cut start must be a date (YYYY-MM-DD)")

    @field_validator("office_start", "office_end")
    @classmethod
    def times(cls, v):
        if not TIME_RE.match(v):
            raise ValueError("Time must be HH:MM (24-hour)")
        return v

    @field_validator("working_days")
    @classmethod
    def days(cls, v):
        v = sorted(set(v))
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("Working days must be 0 (Mon) to 6 (Sun)")
        return v

    @model_validator(mode="after")
    def check(self):
        if self.half_day_hours > self.full_day_hours:
            raise ValueError("Half-day hours cannot exceed full-day hours")
        return self
