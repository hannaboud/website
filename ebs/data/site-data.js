/* ============================================================
   EBS WEBSITE CONTENT
   This is the only file you need to edit for routine updates.
   Keep the commas and quotes exactly as in the examples.
   ============================================================ */

const EBS = {

  /* ---------- General ---------- */
  config: {
    email: "contact@ebsduke.com",
    linkedin: "https://www.linkedin.com/company/european-business-society-at-duke/",
    instagram: "https://www.instagram.com/ebs.duke/",
    dukeGroups: "https://duke.campusgroups.com/ebs/home/"
  },

  stats: [
    { number: "70+",  label: "consultants" },
    { number: "100+", label: "members" },
    { number: "30+",  label: "clients served" },
    { number: "2024", label: "founded at Duke" }
  ],

  /* ---------- Team ----------
     Optional for each person:  classOf: "2027",  linkedin: "https://www.linkedin.com/in/..."
     Example: { name: "First Last", role: "Consultant", classOf: "2028", linkedin: "https://..." },  */
  team: {
    founders: [
      { name: "Hanna Boudara",          role: "Co-founder", classOf: "2027", linkedin: "https://www.linkedin.com/in/hannaboudara/" },
      { name: "Alex Piña-Nadal",        role: "Co-founder", classOf: "2027", linkedin: "https://www.linkedin.com/in/alexpinyanadal/" },
      { name: "Can Varas",              role: "Co-founder", classOf: "2027", linkedin: "https://www.linkedin.com/in/canvaras/" },
      { name: "Ayan Shwartzenberg",     role: "Co-founder", classOf: "2027" },
      { name: "Carlota Herrera Benito", role: "Co-founder", classOf: "2027", linkedin: "https://www.linkedin.com/in/carlota-herrera-benito-b09287230/" }
    ],
    presidents: [
      { name: "Celine Cai",  role: "Co-President", classOf: "2029", linkedin: "https://www.linkedin.com/in/celinecaibc/" },
      { name: "Neev Goenka", role: "Co-President", classOf: "2029", linkedin: "https://www.linkedin.com/in/neev-goenka/" }
    ],
    exec: [
      { name: "Victoria Garcia",  role: "VP of Operations",          classOf: "2029", linkedin: "https://www.linkedin.com/in/victoriagarc%C3%ADaganuzabellver/" },
      { name: "Laura Kammenou",   role: "VP of Communication",       classOf: "2027", linkedin: "https://www.linkedin.com/in/laurakammenou/" },
      { name: "Margaret MacGurn", role: "Director of Operations",    classOf: "2028", linkedin: "https://www.linkedin.com/in/margaret-macgurn/" },
      { name: "Matthew Schnur",   role: "Director of Communication", classOf: "2028", linkedin: "https://www.linkedin.com/in/matthew-schnur-08b569345/" },
      { name: "Prubgeet Singh",   role: "Director of Communication", classOf: "2028", linkedin: "https://www.linkedin.com/in/prubgeet-singh/" }
    ],
    /* Add consultants in the same format. */
    consultants: []
  },

  /* ---------- Events ----------
     date is YEAR-MONTH-DAY. Times use the 24-hour clock ("18:30").
     category must be one of the names in eventCategories.
     link is optional (RSVP form, CampusGroups page...).
                                                                    */
  eventCategories: ["Info session", "Recruitment", "Workshop", "Speaker", "Social", "Deadline"],

  /* Example (copy this line between the [ ] below and change the details):
     { title: "Info session", date: "2026-10-14", start: "18:00", end: "19:00",
       location: "Room name", category: "Info session",
       description: "One sentence about the event.", link: "" },            */
  events: [],

  /* ---------- Projects ---------- */
  projects: [
    { client: "InnovX",        region: "United States",        title: "50-state market analysis",
      summary: "A state-by-state comparison to help a European business accelerator decide where its companies should enter the US market." },
    { client: "RAPTronic",     region: "United States",        title: "US expansion and logistics",
      summary: "In-depth research on entering the US market, including the logistics of getting product to customers." },
    { client: "Monte-Digital", region: "United Arab Emirates", title: "UAE financial landscape research",
      summary: "A study of the financial sector in the UAE to inform the client's regional strategy." }
  ],

  /* ---------- Whitepapers ----------
     Put the PDF in the whitepapers/ folder, then add a line like:
     { title: "Paper title", date: "Spring 2026", summary: "One sentence.", file: "whitepapers/file-name.pdf" },  */
  whitepapers: [],

  /* ---------- Membership FAQ ---------- */
  faq: [
    { q: "How do I apply?",
      a: "Come to an info session at the start of the semester. Attending one is required to take part in rush. Dates are on the Events page." },
    { q: "Do EBS clients pay for projects?",
      a: "No. All EBS projects are pro bono. Clients bring real problems and their time; members get real experience." },
    { q: "What kind of work will I do?",
      a: "Market research, expansion and site selection analysis, pitch deck development, translations and strategy work, in a small team with a project lead." },
    { q: "Who are the clients?",
      a: "Mostly small and mid-sized companies in Europe, the US and the Middle East that want research they don't have time to do themselves." }
  ]
};