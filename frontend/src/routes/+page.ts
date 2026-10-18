// Лендінг — єдина серверно-рендерена сторінка SPA-застосунку:
// page-level override глобального ssr=false у routes/+layout.ts.
// adapter-static згенерує повний HTML — миттєвий перший кадр + SEO.
export const ssr = true;
export const prerender = true;
export const csr = true;
