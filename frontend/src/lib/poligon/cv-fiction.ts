// CV firmowe osoby ćwiczebnej (ćwiczenie „Popraw CV poleceniem AI”, 16.11.2026).
// Zestaw nie przyjmuje tekstu spoza słownika (`poligon-dataset.test.ts`), więc
// treść CV dokłada front. Kształt jak CV z generatora po zapisie w edytorze
// (znaczniki sekcji, role, punkty) — ten sam co w harnessie `/preview/cv-editor`.

export const CV_FICTION_TERMS = ["Scrum", "Jira"] as const;

export function cvFictionHtml(fullName: string): string {
  return (
    `<h1>Senior Project Manager – ${fullName}</h1>` +
    "<p><strong>Rozważany na stanowisko:</strong> Senior Project Manager (bankowość)</p><hr>" +
    '<h2 data-cv-section="why_points">DLACZEGO NASZ KANDYDAT?</h2>' +
    "<ul><li><p>9 lat jako Project Manager w bankowości: migracja systemu płatności i bankowość mobilna.</p></li>" +
    "<li><p>Prowadziła cztery zespoły i raportowała do komitetu sterującego.</p></li></ul>" +
    '<h2 data-cv-section="skills">UMIEJĘTNOŚCI</h2>' +
    "<p><strong>Metodyki: </strong>Scrum, SAFe, PRINCE2</p>" +
    "<p><strong>Narzędzia: </strong>Jira, Confluence, MS Project</p>" +
    '<h2 data-cv-section="languages">JĘZYKI</h2><p>polski – ojczysty · angielski – B2</p>' +
    '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' +
    '<p data-cv-section="role"><strong>Senior Project Manager</strong> 03.2021 – obecnie</p>' +
    '<p data-cv-section="employer">Firma Przykładowa S.A. · Bankowość</p>' +
    '<p data-cv-section="duties_label">Zakres zadań:</p>' +
    "<ul><li><p>Prowadzenie programu migracji systemu płatności: harmonogram, ryzyka i budżet.</p></li>" +
    "<li><p>Koordynacja czterech zespołów w Scrum i planowanie w Jira.</p></li>" +
    "<li><p>Raporty dla komitetu sterującego i praca z dostawcą zewnętrznym.</p></li></ul>" +
    '<p data-cv-section="technologies">Technologie: Jira, Confluence, MS Project</p>' +
    '<p data-cv-section="role"><strong>Project Manager</strong> 01.2017 – 02.2021</p>' +
    '<p data-cv-section="employer">Software House Przykład sp. z o.o. · IT</p>' +
    '<p data-cv-section="duties_label">Zakres zadań:</p>' +
    "<ul><li><p>Wdrożenie nowej bankowości mobilnej dla klienta z sektora finansowego.</p></li>" +
    "<li><p>Planowanie sprintów i przeglądy z klientem.</p></li></ul>" +
    '<p data-cv-section="technologies">Technologie: Jira, Confluence</p>' +
    // Starsza rola spoza zawodu z punktu 1: QC liczy z niej cały staż i
    // proponuje „N lat w IT, w tym M jako Project Manager” (nowość „Lata
    // w punkcie 1”, `backend/scripts/poligon_cv_practice.py`).
    '<p data-cv-section="role"><strong>Analityk biznesowy</strong> 09.2013 – 12.2016</p>' +
    '<p data-cv-section="employer">Firma Przykładowa S.A. · Bankowość</p>' +
    '<p data-cv-section="duties_label">Zakres zadań:</p>' +
    "<ul><li><p>Analiza wymagań do systemu płatności i odbiory z biznesem.</p></li></ul>"
  );
}
