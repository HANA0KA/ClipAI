import type { Metadata } from "next";
import { Anton, Archivo, Montserrat } from "next/font/google";
import { AppHeader } from "@/components/clipai/app-header";
import { Providers } from "./providers";
import "./globals.css";

// Una sola familia para la interfaz: Archivo variable (el eje de ancho separa
// títulos condensados del cuerpo). Montserrat y Anton solo para previsualizar
// las plantillas de subtítulos tal como se queman en el video.
const archivo = Archivo({ subsets: ["latin"], variable: "--font-sans", axes: ["wdth"] });
const montserrat = Montserrat({ subsets: ["latin"], weight: ["800"], variable: "--font-montserrat" });
const anton = Anton({ subsets: ["latin"], weight: ["400"], variable: "--font-anton" });

export const metadata: Metadata = {
  title: "ClipAI",
  description: "Clips verticales con IA desde tus videos, en tu computadora.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="es" className={`dark ${archivo.variable} ${montserrat.variable} ${anton.variable} h-full antialiased`}>
      <body className="min-h-full bg-background text-foreground">
        <Providers>
          <AppHeader />
          <main className="mx-auto w-full max-w-[1440px] px-4 pb-16 sm:px-6">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
