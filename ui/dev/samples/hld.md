# Clinic Booking App: High-Level Design

## Overview

Three parts: a patient web app, a front-desk dashboard, and one small API with a database. Reminders run as a scheduled job.

## Parts

- **Patient app.** A mobile-first web page. No install.
- **Front-desk dashboard.** A single day view, updated live.
- **API.** Handles bookings, slots and reminders.
- **Database.** Clinics, services, slots, bookings.
- **Reminder job.** Runs every hour and sends messages for the next day.

## How a booking flows

1. The patient picks a service and sees free slots.
2. The API holds the slot for five minutes.
3. The patient confirms; the booking is saved.
4. The dashboard shows it straight away.

## Choices still open

- Which messaging provider to use for WhatsApp.
- Whether to support more than one clinic per account.
