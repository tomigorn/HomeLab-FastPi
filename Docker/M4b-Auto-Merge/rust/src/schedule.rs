use chrono::{Datelike, Days, NaiveDateTime, NaiveTime};

/// Next `dow` (Mon=0 .. Sun=6, any integer wraps) at hour:minute, strictly after `now` (local wall time).
pub fn next_sweep(dow: i64, time: NaiveTime, now: NaiveDateTime) -> NaiveDateTime {
    let days = (dow - i64::from(now.weekday().num_days_from_monday())).rem_euclid(7) as u64;
    let target = now.date().and_time(time) + Days::new(days);
    if target <= now {
        target + Days::new(7)
    } else {
        target
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::NaiveDate;

    fn at(y: i32, m: u32, d: u32, h: u32, mi: u32) -> NaiveDateTime {
        NaiveDate::from_ymd_opt(y, m, d).unwrap().and_hms_opt(h, mi, 0).unwrap()
    }

    #[test]
    fn same_week_later() {
        // 2026-11-09 is a Monday
        assert_eq!(next_sweep(5, NaiveTime::from_hms_opt(4, 0, 0).unwrap(), at(2026, 11, 9, 2, 51)), at(2026, 11, 14, 4, 0));
    }

    #[test]
    fn today_later_and_today_passed() {
        let t = NaiveTime::from_hms_opt(4, 0, 0).unwrap();
        assert_eq!(next_sweep(0, t, at(2026, 11, 9, 3, 59)), at(2026, 11, 9, 4, 0));
        assert_eq!(next_sweep(0, t, at(2026, 11, 9, 4, 0)), at(2026, 11, 16, 4, 0));
        assert_eq!(next_sweep(0, t, at(2026, 11, 9, 4, 1)), at(2026, 11, 16, 4, 0));
    }

    #[test]
    fn day_number_wraps_like_python_modulo() {
        let t = NaiveTime::from_hms_opt(4, 0, 0).unwrap();
        assert_eq!(next_sweep(12, t, at(2026, 11, 9, 5, 0)), next_sweep(5, t, at(2026, 11, 9, 5, 0)));
        assert_eq!(next_sweep(-1, t, at(2026, 11, 9, 5, 0)), at(2026, 11, 15, 4, 0));
    }

    #[test]
    fn crosses_month_and_year() {
        assert_eq!(next_sweep(5, NaiveTime::from_hms_opt(4, 0, 0).unwrap(), at(2026, 12, 31, 10, 0)), at(2027, 1, 2, 4, 0));
    }
}
