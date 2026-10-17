import { ClipEditor } from "@/components/clipai/clip-editor";

export default async function ClipPage({ params }: PageProps<"/clips/[id]">) {
  const { id } = await params;
  // key: al pasar de un clip a otro el estudio se monta de nuevo (estado,
  // historial y reproductores); si no, React reutiliza el mismo <video>, que
  // con la misma fuente seguía sonando.
  return <ClipEditor key={id} id={id} />;
}
