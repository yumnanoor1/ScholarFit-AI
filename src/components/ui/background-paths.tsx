interface SplashScreenProps {
    onExplore?: () => void;
    onVideoEnded?: () => void;
}

export function BackgroundPaths({ onExplore, onVideoEnded }: SplashScreenProps) {
    return (
        <main className="fixed inset-0 overflow-hidden bg-black">
            <video
                className="h-full w-full object-cover"
                autoPlay
                muted
                playsInline
                preload="auto"
                tabIndex={-1}
                aria-hidden="true"
                onEnded={onVideoEnded}
                onError={onExplore}
            >
                <source src="/videos/fitscholar-intro.mp4" type="video/mp4" />
            </video>
            <button
                type="button"
                className="absolute inset-0 cursor-pointer border-0 bg-transparent p-0 focus-visible:outline focus-visible:outline-2 focus-visible:outline-white"
                aria-label="Skip splash video"
                onClick={onExplore}
            />
        </main>
    );
}
