# CAPY - Club Assistant in Python

[![Continuous Integration (CI)](https://github.com/CApy-RPI/capy-discord/actions/workflows/main.yml/badge.svg)](https://github.com/CApy-RPI/capy-discord/actions/workflows/main.yml)
![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)

## **Overview**

**CAPY** is an Open Source initiative aimed at redefining the student experience by improving access to campus resources and opportunities. Originally founded at Rensselaer Polytechnic Institute (RPI), CAPY serves as a unified platform to streamline club management, student engagement, and academic communication.

Our current MVP is a powerful **Discord application** that extends organizational communication with interactive features like automated announcements, event hosting, and cross-channel profiles.

## **The Vision**

Beyond just a Discord bot, we believe CAPY should be a platform where developers "dream and create freely to benefit the student body." Our roadmap includes:

- **Scaling:** Expanding from Discord to Slack, web, and standalone executable applications.
- **B2B Services:** Assisting club officers with profile management, attendance tracking, and engagement metrics.
- **Academic Integration:** Helping professors manage course servers, reminders, and student participation.
- **Student Connectivity:** Facilitating alumni lookups, study group formations, and shared event hubs.

## **Key Features**

- **Student Verification:** Secure onboarding for campus organizations.
- **Profile Management:** Cross-channel profiles to highlight student involvement.
- **Event Advertising:** Streamlined hosting and advertising for club events.
- **Aesthetic UX:** Focus on a clean, "dumb" UI (via the `CallbackModal` pattern) to keep logic decoupled and efficient.

### **Upcoming Features (2026 Roadmap)**

- **"When is Good" Scheduling:** Integrated meeting coordination within Discord.
- **Automated Digests:** Summaries for mentions, announcements, and class activities.
- **Social Engagement:** Mini-games (Chess, etc.) to drive community interaction.
- **Calendar Integration:** Support for external Calendar APIs.

---

## **Technical Architecture**

CAPY Discord is built with scalability and clean code in mind, following a **Feature Folder** structure:

- **Decoupled UI:** Uses the `CallbackModal` pattern to separate business logic from Discord's UI components.
- **Single Entry Points:** Utilizes subcommands and choices to keep the global command list clean.
- **Modern Tooling:** Managed by `uv` for lightning-fast dependency management and task execution.

## **Getting Started**

### **Prerequisites**

- Python 3.9+
- [uv](https://github.com/astral-sh/uv) (Recommended for dependency management)

### **Installation**

1. **Clone the repository:**

   ```bash
   git clone https://github.com/CApy-RPI/capy-discord.git
   cd capy-discord
   ```

2. **Sync dependencies:**

   ```bash
   uv sync
   ```

3. **Configuration:**
   Create a `.env` file in the root directory and add your Discord bot `TOKEN` and other required environment variables.

### **Development Commands**

We use `uv run task` to ensure consistent execution:

- **Start the bot:** `uv run task start`
- **Lint & Type Check:** `uv run task lint` (Run this before every commit!)
- **Run Tests:** `uv run task test`

---

## **Project Team**

### **Founders**

- **Jason Zhang** ([zhangy96@rpi.edu](mailto:zhangy96@rpi.edu))
- **Shamik Karkhanis** ([karkhs@rpi.edu](mailto:karkhs@rpi.edu))

### Current Contributors

*Thank you for your continuous effort into advancing our mission:*
Sayed Imtiazuddin, Jonathan Green, Ethan Beloff, Cindy Yang

### **Past Contributors**

*We are grateful for the contributions of our past members:*
Vincent Shi, Pradeep Giri, Zane Brotherton, Gabriel Conner, Gianluca Zhang, Caleb Alemu, Kaylee Xie, Elias Cueto, Thomas Doherty, Tag Ciccone, Daniel Aube, Brian Ng

## **Contributing**

We welcome campus participation!

1. Fork the repo and create your feature branch.
2. Adhere to the **Scalable Cog Patterns** outlined in `AGENTS.md`.
3. Ensure all changes pass `uv run task lint`.
4. Open a Pull Request with a clear description of your changes.

## **License**

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
