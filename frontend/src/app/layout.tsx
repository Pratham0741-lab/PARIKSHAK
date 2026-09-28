import type { Metadata } from 'next';
import './globals.css';
import { Navbar } from '@/components/Navbar';

export const metadata: Metadata = {
  title: 'ISRO SIH26170 | Aerospace Burn-In Screening & Analytics',
  description: 'Local Deterministic Anomaly Detection, Early Drift Forecasting, and QA Review Workbench',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark h-full bg-[#090d16] text-slate-100 antialiased">
      <body className="min-h-full flex flex-col bg-[#090d16] text-slate-100 bg-grid-aerospace">
        <Navbar />
        <main className="flex-1 pb-16">{children}</main>
      </body>
    </html>
  );
}
