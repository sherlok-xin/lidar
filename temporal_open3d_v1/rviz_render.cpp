#include <Ogre.h>
#include <OgreHardwarePixelBuffer.h>
#include <OgreRenderTexture.h>
#include <cstdio>

extern "C" int save_review_target(const char* destination) {
    const char* texture_name = "mining_review_offscreen_target";
    try {
        Ogre::RenderSystem* system = Ogre::Root::getSingleton().getRenderSystem();
        Ogre::RenderSystem::RenderTargetIterator targets = system->getRenderTargetIterator();
        Ogre::Viewport* chosen = nullptr;
        unsigned int size = 0;
        while (targets.hasMoreElements()) {
            Ogre::RenderTarget* target = targets.getNext();
            if (dynamic_cast<Ogre::RenderWindow*>(target) == nullptr) continue;
            for (unsigned int pos=0; pos<target->getNumViewports(); ++pos) {
                Ogre::Viewport* view=target->getViewport(pos);
                unsigned int pixels=view->getActualWidth()*view->getActualHeight();
                if (view->getCamera() && pixels>size) { chosen=view; size=pixels; }
            }
        }
        if (!chosen || size<16384) return 1;
        Ogre::TexturePtr texture = Ogre::TextureManager::getSingleton().createManual(texture_name,
            Ogre::ResourceGroupManager::DEFAULT_RESOURCE_GROUP_NAME, Ogre::TEX_TYPE_2D,
            chosen->getActualWidth(),chosen->getActualHeight(),0,Ogre::PF_R8G8B8,Ogre::TU_RENDERTARGET);
        Ogre::RenderTexture* target = texture->getBuffer()->getRenderTarget();
        target->setAutoUpdated(false);
        Ogre::Camera* source_camera = chosen->getCamera();
        Ogre::SceneManager* scene = source_camera->getSceneManager();
        Ogre::Camera* snapshot_camera = scene->createCamera("mining_review_snapshot_camera");
        snapshot_camera->setNearClipDistance(source_camera->getNearClipDistance());
        snapshot_camera->setFarClipDistance(source_camera->getFarClipDistance());
        snapshot_camera->setCustomViewMatrix(true,source_camera->getViewMatrix());
        snapshot_camera->setCustomProjectionMatrix(true,source_camera->getProjectionMatrix());
        Ogre::Viewport* capture = target->addViewport(snapshot_camera);
        capture->setBackgroundColour(chosen->getBackgroundColour());
        capture->setVisibilityMask(chosen->getVisibilityMask());
        capture->setOverlaysEnabled(false);
        target->update();
        target->writeContentsToFile(destination);
        target->removeAllViewports();
        scene->destroyCamera(snapshot_camera);
        Ogre::TextureManager::getSingleton().remove(texture_name);
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr,"render target export: %s\n",error.what());
        return 2;
    }
}
