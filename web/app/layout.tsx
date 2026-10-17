import type { Metadata } from "next";
import { Anton, Bricolage_Grotesque, DM_Sans, Montserrat } from "next/font/google";
import { AppHeader } from "@/components/clipai/app-header";
import { Providers } from "./providers";
import "./globals.css";

// Tipografía de cojeev-ui: Bricolage Grotesque para títulos (su eje de ancho los
// condensa) y DM Sans para la interfaz. Montserrat y Anton solo para previsualizar
// las plantillas de subtítulos tal como se queman en el video.
const bricolage = Bricolage_Grotesque({ subsets: ["latin"], variable: "--font-bricolage", axes: ["opsz", "wdth"] });
const dmSans = DM_Sans({ subsets: ["latin"], variable: "--font-dmsans", axes: ["opsz"] });
const montserrat = Montserrat({ subsets: ["latin"], weight: ["800"], variable: "--font-montserrat" });
const anton = Anton({ subsets: ["latin"], weight: ["400"], variable: "--font-anton" });

export const metadata: Metadata = {
  title: "ClipAI",
  description: "Clips verticales con IA desde tus videos, en tu computadora.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="es" data-mode="dark" className={`dark ${bricolage.variable} ${dmSans.variable} ${montserrat.variable} ${anton.variable} h-full antialiased`}>
      <body className="min-h-full bg-background text-foreground">
        <Providers>
          <AppHeader />
          <main className="mx-auto w-full max-w-[1440px] px-4 pb-16 sm:px-6">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
