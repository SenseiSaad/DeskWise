# Startup Test Kit — How to Upload & Test Everything in 5 Minutes

Upload the 8 files in this `test_startup_docs/` folder under **Workspace -> Documents** with the settings below to test **AI Q&A, RBAC Permissions, Explainability, Break-Glass, Audit Log, and Document/Email/NDA Generation**.

---

## 1. Create 2 Departments First (Workspace -> Members -> Departments)
- `Engineering`
- `Finance`

## 2. Upload Settings for Each File

| File | Who can see this? | How confidential? | Mark as Template? |
| --- | --- | --- | --- |
| `01_Policy_Company_Handbook_and_Leave_STANDARD.md` | **Everyone** | **Standard** | No |
| `02_Policy_Engineering_and_IT_Security_INTERNAL.md` | **My department** (`Engineering`) | **Internal** | No |
| `03_Policy_Finance_Payroll_and_Salary_Bands_CONFIDENTIAL.md` | **My department** (`Finance`) | **Confidential** | No |
| `04_Notes_Founder_Board_and_Acquisition_RESTRICTED.md` | **Only selected people** *(upload from a non-admin employee account to test Admin Break-Glass!)* | **Internal** or **Confidential** | No |
| `05_Template_Email_Sick_and_Casual_Leave.md` | **Everyone** | **Standard** | **Yes** (`email`) |
| `06_Template_Application_Work_From_Home_and_Expense.md` | **Everyone** | **Standard** | **Yes** (`form`) |
| `07_Template_Letter_Employment_and_Experience.md` | **Everyone** | **Standard** | **Yes** (`form`) |
| `08_Template_Legal_Mutual_NDA.md` | **Everyone** *(or Finance)* | **Internal** | **Yes** (`policy`) |

*(Tip: When editing a document in **Documents -> Edit**, toggle **Template** ON for files `05`–`08`, or Deskwise will also auto-detect their `TPL-...` template headers!)*

---

## 3. Exact Prompts to Test in **Ask AI**

1. **Standard Policy Q&A (works for Intern / Viewer, Employee, and Admin):**
   > `How many paid annual leave and sick days do we get, and what is the home-office stipend?`
2. **Department Isolation Test (works for Engineering Employee; refused for Intern / Viewer):**
   > `Can we deploy to production on Friday afternoon, and what is the SEV-1 incident phone number?`
3. **The 30-Second "Payroll Blocked" Demo (ask as regular Employee -> REFUSED; ask as Admin -> ANSWERED):**
   > `What are the 2026 monthly salary bands for a Senior Engineer and the CEO?`
   - Then switch to **Admin -> Documents** -> click **"Why can't they see?"** on file `03` and pick the Employee -> hold 4–5 seconds on the blocking rule chain + **Audit Log**!
4. **Generate Ready-to-Send Sick Leave Email (uses your Profile + Template `05`):**
   > `Write me a sick leave email for tomorrow and Friday because of fever, Ali will cover for me.`
5. **Generate Employment Verification Letter (Template `07`):**
   > `Generate an employment verification letter for me as a Full-Time Active employee.`
6. **Generate a Filled Mutual NDA (Template `08`):**
   > `Draft a 2-year Mutual NDA with Acme Robotics (contact: Sara Khan, sara@acmerobotics.io) effective Dec 1, 2026 under DIFC Dubai law for AI pilot evaluation.`
