import gym
from gym.core import Wrapper
import time
from glob import glob
import csv
import os.path as osp
import json
import pandas

__all__ = ['EpisodeMonitor', 'get_monitor_files', 'load_results']


class EpisodeMonitor(Wrapper):
    EXT = "monitor.csv"
    f = None

    def __init__(self, env, filename, allow_early_resets=False, reset_keywords=()):
        Wrapper.__init__(self, env=env)
        self.tstart_ep0 = time.time()
        self.tstart_ep_current = None  # by .reset()
        if filename is None:
            self.f = None
            self.logger = None
        else:
            if not filename.endswith(EpisodeMonitor.EXT):
                if osp.isdir(filename):
                    filename = osp.join(filename, EpisodeMonitor.EXT)
                else:
                    filename = filename + "." + EpisodeMonitor.EXT
            self.f = open(filename, "wt")
            self.f.write('#%s\n'%json.dumps({"t_start": self.tstart_ep0, "gym_version": gym.__version__,
                "env_id": env.spec.id if env.spec else 'Unknown'}))
            self.logger = csv.DictWriter(self.f, fieldnames=('r', 'l', 't')+reset_keywords)
            self.logger.writeheader()

        self.reset_keywords = reset_keywords
        self.allow_early_resets = allow_early_resets
        self.rewards = None
        self.needs_reset = True
        self.episode_rewards = []
        self.episode_steps = []
        self.episode_times = []
        self.total_steps = 0
        self.current_reset_info = {} # extra info about the current episode, that was passed in during reset()

    def _reset(self, **kwargs):
        if not self.allow_early_resets and not self.needs_reset:
            raise RuntimeError("Tried to reset an environment before done. If you want to allow early resets, wrap your env with EpisodeMonitor(env, path, allow_early_resets=True)")
        self.rewards = []
        self.needs_reset = False
        self.tstart_ep_current = time.time()
        for k in self.reset_keywords:
            v = kwargs.get(k)
            if v is None:
                raise ValueError('Expected you to pass kwarg %s into reset'%k)
            self.current_reset_info[k] = v
        return self.env.reset(**kwargs)

    def _step(self, action):
        if self.needs_reset:
            raise RuntimeError("Tried to step environment that needs reset")
        ob, rew, done, info = self.env.step(action)
        self.rewards.append(rew)
        if done:
            self.needs_reset = True
            eprew = round(sum(self.rewards), 6)
            epsteps = len(self.rewards)
            eptime = round(time.time() - self.tstart_ep_current, 6)
            epinfo = {
                "total_reward": eprew,
                "steps": epsteps,
                "time": eptime,
                "time_from_0": round(time.time() - self.tstart_ep0, 6),
            }
            epinfo.update(self.current_reset_info)
            if self.logger:
                self.logger.writerow(epinfo)
                self.f.flush()
            self.episode_rewards.append(eprew)
            self.episode_steps.append(epsteps)
            self.episode_times.append(eptime)
            info['episode'] = epinfo
        self.total_steps += 1
        return (ob, rew, done, info)

    def close(self):
        if self.f is not None:
            self.f.close()

    def get_total_steps(self):
        return self.total_steps

    def get_episode_rewards(self):
        return self.episode_rewards

    def get_episode_steps(self):
        return self.episode_steps

    def get_episode_times(self):
        return self.episode_times


class LoadMonitorResultsError(Exception):
    pass


def get_monitor_files(dir):
    return glob(osp.join(dir, "*" + EpisodeMonitor.EXT))


def load_results(dir):
    monitor_files = glob(osp.join(dir, "*monitor.*")) # get both csv and (old) json files
    if not monitor_files:
        raise LoadMonitorResultsError("no monitor files of the form *%s found in %s" % (EpisodeMonitor.EXT, dir))
    dfs = []
    headers = []
    for fname in monitor_files:
        with open(fname, 'rt') as fh:
            if fname.endswith('csv'):
                firstline = fh.readline()
                assert firstline[0] == '#'
                header = json.loads(firstline[1:])
                df = pandas.read_csv(fh, index_col=None)
                headers.append(header)
            elif fname.endswith('json'): # Deprecated json format
                episodes = []
                lines = fh.readlines()
                header = json.loads(lines[0])
                headers.append(header)
                for line in lines[1:]:
                    episode = json.loads(line)
                    episodes.append(episode)
                df = pandas.DataFrame(episodes)
        df['t'] += header['t_start']
        dfs.append(df)
    df = pandas.concat(dfs)
    df.sort_values('t', inplace=True)
    df['t'] -= min(header['t_start'] for header in headers)
    df.headers = headers # HACK to preserve backwards compatibility
    return df