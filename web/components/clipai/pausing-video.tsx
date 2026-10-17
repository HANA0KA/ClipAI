"use client";

import { forwardRef, useImperativeHandle, useLayoutEffect, useRef } from "react";

/**
 * `<video>` que se pausa al desmontarse o al ocultarse. Un video fuera de la
 * vista (pestaña oculta con CSS, ruta preservada por Next con `<Activity>`)
 * sigue sonando si nadie lo pausa: la guía de Next lo pide explícito.
 */
export const PausingVideo = forwardRef<HTMLVideoElement, React.ComponentProps<"video">>(function PausingVideo(
  props,
  ref,
) {
  const video = useRef<HTMLVideoElement>(null);
  useImperativeHandle(ref, () => video.current as HTMLVideoElement);
  useLayoutEffect(() => {
    const el = video.current;
    return () => el?.pause();
  }, []);
  return <video ref={video} {...props} />;
});
